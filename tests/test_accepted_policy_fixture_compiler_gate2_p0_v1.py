"""Controlled Windows P0 capture tests.

No wsl.exe, ctr, Docker, compiler, fixture payload, or root action is run.
Injected effects are labeled controlled and are not physical acceptance.
Native tests patch the factory and the process launcher. They do not invoke it.
"""
import asyncio
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.fixtures import accepted_policy_fixture_compiler_gate2_p0_v1 as p0


PARENT = "sha256:3c8de05108c6b3259458437ceacd7d9f8fc1ae08dc1e79889953e6865705f34e"
FOREIGN_ENGINE = "ffffffff-ffff-ffff-ffff-ffffffffffff"
OUT = "C:/gate2/p0-out"
UNC_OUT = "//wsl$/Ubuntu/gate2/p0-out"
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def binding(**overrides):
    value = {
        "known_engine_id": p0.KNOWN_ENGINE_ID,
        "boot": {"boot_id": "boot-extern-001"},
        "provenance": {
            "source": "external",
            "observer": "ordinary_api",
            "engine_id": p0.KNOWN_ENGINE_ID,
            "boot_id": "boot-extern-001",
        },
    }
    for key, item in overrides.items():
        if key == "provenance":
            value["provenance"].update(item)
        elif key == "boot":
            value["boot"].update(item)
        else:
            value[key] = item
    return value


def info_bytes(name=None, kind="Committed", trailing="\n"):
    payload = {
        "Kind": kind,
        "Name": p0.CHAIN_ID if name is None else name,
    }
    return (json.dumps(payload, sort_keys=True) + trailing).encode("utf-8")


def ls_bytes(rows):
    lines = ["KEY PARENT KIND"]
    for key, parent, kind in rows:
        if parent:
            lines.append(key + " " + parent + " " + kind)
        else:
            lines.append(key + " " + kind)
    return ("\n".join(lines) + "\n").encode("utf-8")


def chain_row():
    return (p0.CHAIN_ID, PARENT, "Committed")


def success_scripts():
    return [
        {"stdout": b"0\n", "stderr": b"", "returncode": 0},
        {"stdout": info_bytes(), "stderr": b"", "returncode": 0},
        {"stdout": ls_bytes([chain_row()]), "stderr": b"", "returncode": 0},
    ]


class ControlledEffects:
    """In-memory process and file seam. Never creates a process."""

    controlled = True
    physical_acceptance = False
    label = "controlled"

    def __init__(self, scripts, **options):
        self.scripts = [dict(item) for item in scripts]
        for item in self.scripts:
            item.setdefault("stdout", b"")
            item.setdefault("stderr", b"")
            item.setdefault("returncode", 0)
            item.setdefault("exit_when", "immediate")
            item.setdefault("stdout_eof", True)
            item.setdefault("stderr_eof", True)
            item.setdefault("read_dt", 0.0)
            item.setdefault("code_after_terminate", None)
            item.setdefault("eof_after_terminate", False)
            item["stdout_off"] = 0
            item["stderr_off"] = 0
        self.t = float(options.get("t0", 0.0))
        self.spawn_dt = float(options.get("spawn_dt", 0.0))
        self.fsync_dt = float(options.get("fsync_dt", 0.0))
        self.write_dt = float(options.get("write_dt", 0.0))
        self.close_dt = float(options.get("close_dt", 0.0))
        self.fail_write = bool(options.get("fail_write", False))
        self.fail_fsync = bool(options.get("fail_fsync", False))
        self.fail_close = bool(options.get("fail_close", False))
        self.mkdir_error = options.get("mkdir_error")
        self.mkdir_dt = float(options.get("mkdir_dt", 0.0))
        self.close_dt_after = options.get("close_dt_after")
        self.close_ordinal = 0
        self.spawns = []
        self.terminations = []
        self.files = {}
        self.opened = []
        self.read_requests = []
        self.events = []
        self.spawn_calls = 0

    def monotonic(self):
        return self.t

    def spawn(self, argv, env):
        self.spawn_calls += 1
        if self.spawn_calls > len(self.scripts):
            raise AssertionError("spawn exceeded scripted command cap")
        handle = type("Handle", (), {})()
        handle.pid = 4000 + self.spawn_calls
        handle.index = self.spawn_calls - 1
        handle.terminated = False
        handle.identity = ("owned-parent", handle.pid)
        self.spawns.append({
            "argv": list(argv),
            "env": dict(env),
            "t": self.t,
            "handle": handle.identity,
        })
        self.t += self.spawn_dt
        return handle

    def _read(self, handle, max_bytes, stream):
        self.read_requests.append((handle.index, stream, max_bytes))
        script = self.scripts[handle.index]
        self.t += script["read_dt"]
        plan_key = stream + "_plan"
        if plan_key in script:
            plan = script[plan_key]
            if not plan:
                return b""
            item = plan.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        if handle.terminated and script["eof_after_terminate"]:
            return b""
        data = script[stream]
        off_key = stream + "_off"
        off = script[off_key]
        if off >= len(data):
            if script[stream + "_eof"]:
                return b""
            return None
        chunk = data[off:off + max_bytes]
        script[off_key] = off + len(chunk)
        return chunk

    def read_stdout(self, handle, max_bytes):
        return self._read(handle, max_bytes, "stdout")

    def read_stderr(self, handle, max_bytes):
        return self._read(handle, max_bytes, "stderr")

    def poll_exit(self, handle):
        script = self.scripts[handle.index]
        if handle.terminated:
            return script["code_after_terminate"]
        if script["exit_when"] == "immediate":
            return script["returncode"]
        if script["exit_when"] == "after_eof":
            out_done = script["stdout_off"] >= len(script["stdout"]) and script["stdout_eof"]
            err_done = script["stderr_off"] >= len(script["stderr"]) and script["stderr_eof"]
            if out_done and err_done:
                return script["returncode"]
            return None
        return None

    def terminate_owned_parent(self, handle):
        self.terminations.append(handle.identity)
        handle.terminated = True

    def mkdir_fresh(self, path):
        self.events.append(("mkdir", path))
        self.t += self.mkdir_dt
        if self.mkdir_error is not None:
            raise self.mkdir_error
        if path in self.files:
            raise FileExistsError(path)

    def reserve_before_write(self, rounded_bytes):
        self.events.append(("reserve", rounded_bytes))

    def open_exclusive(self, path):
        self.events.append(("open", path))
        if path in self.files:
            raise FileExistsError(path)
        self.files[path] = bytearray()
        self.opened.append(path)
        return path

    def write(self, handle, data):
        self.events.append(("write", handle, len(data)))
        self.t += self.write_dt
        if self.fail_write:
            raise OSError("controlled write failure")
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("write requires bytes")
        self.files[handle] += data
        return len(data)

    def fsync(self, handle):
        self.events.append(("fsync", handle))
        self.t += self.fsync_dt
        if self.fail_fsync:
            raise OSError("controlled fsync failure")

    def close(self, handle):
        self.events.append(("close", handle))
        self.close_ordinal += 1
        if self.close_dt_after is None or self.close_ordinal > self.close_dt_after:
            self.t += self.close_dt
        if self.fail_close:
            raise OSError("controlled close failure")


def collect(output_dir, sealed, effects):
    return p0.collect_p0_v1(output_dir, sealed, effects=effects)


def collect_native(output_dir, sealed, effects, commit=COMMIT, *, native_platform=True, factory_dt=0.0):
    original = p0.windows_native_p0_effects

    def factory():
        factory.calls += 1
        effects.t += factory_dt
        return effects

    factory.calls = 0
    p0.windows_native_p0_effects = factory
    try:
        with patch.object(p0.time, "monotonic", effects.monotonic):
            if native_platform:
                with patch.object(p0.os, "name", "nt"):
                    result = p0.collect_native_p0_v1(
                        output_dir, sealed, reviewed_code_commit=commit,
                    )
            else:
                result = p0.collect_native_p0_v1(
                    output_dir, sealed, reviewed_code_commit=commit,
                )
    finally:
        p0.windows_native_p0_effects = original
    result["__factory_calls"] = factory.calls
    return result


def file_named(effects, name):
    matches = [path for path in effects.files if path.endswith("/" + name) or path.endswith("\\" + name)]
    if len(matches) != 1:
        raise AssertionError((name, matches))
    return matches[0], bytes(effects.files[matches[0]])


class PureContractTests(unittest.TestCase):
    def test_signature_constants_and_phase_reserves_do_not_reset(self):
        signature = inspect.signature(p0.collect_p0_v1)
        self.assertEqual(list(signature.parameters), ["output_dir", "sealed_binding", "effects"])
        self.assertEqual(
            signature.parameters["effects"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )
        self.assertTrue(inspect.iscoroutinefunction(p0.collect_p0_v1_async))
        self.assertEqual(p0.ABSOLUTE_DEADLINE_S, 30.0)
        self.assertEqual(p0.PER_COMMAND_DEADLINE_S, 10.0)
        self.assertEqual(p0.STDOUT_CAPS, {"id": 16, "snapshot_info": 65536, "snapshot_ls": 262144})
        self.assertEqual(p0.STDERR_COMBINED_CAP, 16384)
        self.assertEqual(p0.CONTROL_RECORD_CAP, 8192)
        self.assertEqual(p0.COMPLETION_RECORD_CAP, 4096)
        self.assertEqual(p0.METADATA_COMBINED_CAP, 12288)
        self.assertEqual(p0.METADATA_COPY_CAP, 12288)
        self.assertEqual(p0.INODE_BYTES, 256)
        self.assertEqual(p0.P0_FORMS_CEILING, 384 * 1024)
        self.assertLessEqual(p0.P0_FORMS_CEILING, p0.CODE_P0_ALLOCATION)
        early = p0.command_phase_deadlines(0.0, 30.0)
        self.assertEqual(early["cmd_deadline"], 10.0)
        self.assertEqual(early["termination_deadline"], 9.0)
        self.assertEqual(early["capture_deadline"], 7.5)
        late = p0.command_phase_deadlines(25.0, 30.0)
        self.assertEqual(late["cmd_deadline"], 30.0)
        self.assertLess(late["cmd_deadline"] - 25.0, 10.0)
        self.assertEqual(late["capture_deadline"], 27.5)
        self.assertLess(late["capture_deadline"], late["termination_deadline"])
        self.assertLess(late["termination_deadline"], late["cmd_deadline"])

    def test_fixed_argv_env_and_ordinary_runner_identity(self):
        env = p0.fixed_environment()
        self.assertEqual(env, {
            "SystemRoot": "C:/Windows",
            "WINDIR": "C:/Windows",
            "PATH": "C:/Windows/System32;C:/Windows",
        })
        self.assertNotIn("WSLENV", env)
        self.assertNotIn("LD_PRELOAD", env)
        self.assertNotIn("LD_LIBRARY_PATH", env)
        argv = [p0.fixed_argv(name) for name in p0.COMMAND_ORDER]
        self.assertEqual([item[0] for item in argv], [p0.WSL_EXE] * 3)
        self.assertEqual(p0.COMMAND_ORDER, ("id", "snapshot_info", "snapshot_ls"))
        for item in argv:
            self.assertEqual(item[1:8], ["-d", "Ubuntu", "-u", "root", "--cd", "/", "--exec"])
            self.assertNotIn("bash", item)
            self.assertNotIn("sh", item)
        self.assertEqual(argv[0][8:], ["/usr/bin/id", "-u"])
        self.assertEqual(argv[1][8:], [
            "/usr/bin/ctr", "-n", "moby", "snapshots", "--snapshotter", "overlayfs",
            "info", p0.CHAIN_ID,
        ])
        self.assertEqual(argv[2][8:], [
            "/usr/bin/ctr", "-n", "moby", "snapshots", "--snapshotter", "overlayfs", "ls",
        ])
        self.assertEqual(p0.ORDINARY_CD_UID_GID, (1000, 1000))

    def test_validation_helpers_pin_uid_chain_listing_and_engine(self):
        self.assertTrue(p0.validate_id_stdout(b"0\n")["ok"])
        self.assertIn("id_uid_not_zero", p0.validate_id_stdout(b"1000\n")["causes"])
        self.assertIn("id_stdout_not_exact_zero_newline", p0.validate_id_stdout(b"0\r\n")["causes"])
        self.assertNotIn("id_uid_not_zero", p0.validate_id_stdout(b"0\r\n")["causes"])
        good_info = p0.validate_snapshot_info(info_bytes())
        self.assertTrue(good_info["ok"])
        self.assertIn(
            "snapshot_info_name_mismatch",
            p0.validate_snapshot_info(info_bytes(name="sha256:" + "ab" * 32))["causes"],
        )
        self.assertIn(
            "snapshot_info_kind_not_committed",
            p0.validate_snapshot_info(info_bytes(kind="Active"))["causes"],
        )
        self.assertIn("snapshot_info_json_invalid", p0.validate_snapshot_info(b"{")["causes"])
        self.assertTrue(p0.validate_snapshot_ls(ls_bytes([chain_row()]))["ok"])
        child_only = ls_bytes([
            ("sha256:" + "11" * 32, p0.CHAIN_ID, "Committed"),
        ])
        self.assertIn("snapshot_ls_chain_row_not_exactly_one", p0.validate_snapshot_ls(child_only)["causes"])
        duplicated = ls_bytes([chain_row(), chain_row()])
        self.assertIn(
            "snapshot_ls_chain_row_not_exactly_one",
            p0.validate_snapshot_ls(duplicated)["causes"],
        )
        wrong_kind = ls_bytes([(p0.CHAIN_ID, PARENT, "Active")])
        self.assertIn("snapshot_ls_kind_not_committed", p0.validate_snapshot_ls(wrong_kind)["causes"])
        sealed = p0.validate_sealed_binding(binding())
        self.assertTrue(sealed["ok"])
        self.assertEqual(sealed["bound_engine_id"], p0.KNOWN_ENGINE_ID)
        self.assertFalse(sealed["engine_observed_by_collector"])
        missing = binding()
        del missing["provenance"]["engine_id"]
        missed = p0.validate_sealed_binding(missing)
        self.assertIsNone(missed["bound_engine_id"])
        self.assertIn("engine_provenance_missing", missed["causes"])
        foreign = p0.validate_sealed_binding(binding(provenance={"engine_id": FOREIGN_ENGINE}))
        self.assertEqual(foreign["bound_engine_id"], FOREIGN_ENGINE)
        self.assertIn("engine_provenance_mismatch", foreign["causes"])
        collector_obs = p0.validate_sealed_binding(binding(provenance={"observer": "collector"}))
        self.assertIn("engine_not_externally_bound", collector_obs["causes"])
        guard = binding(provenance={"observer": "c_guard"})
        self.assertTrue(p0.validate_sealed_binding(guard)["ok"])

    def test_inclusive_allocation_and_preencoding_bounds(self):
        self.assertEqual(p0.round_up_allocation(0), 4096)
        self.assertEqual(p0.round_up_allocation(1), 4096)
        self.assertEqual(p0.round_up_allocation(4096), 4096)
        self.assertEqual(p0.round_up_allocation(4097), 8192)
        stdout = (
            p0.round_up_allocation(16)
            + p0.round_up_allocation(64 * 1024)
            + p0.round_up_allocation(256 * 1024)
        )
        self.assertEqual(stdout, 324 * 1024)
        expected = (
            324 * 1024
            + 24 * 1024
            + 4 * 1024
            + 12 * 1024
            + 12 * 1024
            + 9 * 256
        )
        self.assertEqual(expected, 387328)
        worst = p0.maximum_inclusive_charge()
        self.assertEqual(worst, expected)
        self.assertLessEqual(worst, p0.P0_FORMS_CEILING)
        self.assertLessEqual(p0.P0_FORMS_CEILING, 1024 * 1024)
        fat = {"stream": "x" * (p0.CONTROL_RECORD_CAP + 1)}
        self.assertTrue(p0.preencoding_exceeds(fat))
        self.assertFalse(p0.preencoding_exceeds({"schema": "gate2-p0-control.v1", "ok": True}))

    def test_source_uses_no_unbounded_stream_helper(self):
        text = (ROOT / "tests/fixtures/accepted_policy_fixture_compiler_gate2_p0_v1.py").read_text(encoding="utf-8")
        for banned in ("communicate(", "capture_output", "readall(", "read_all("):
            self.assertNotIn(banned, text)


class CaptureTests(unittest.TestCase):
    def test_success_is_three_fixed_calls_and_returns_facts_not_stream_bodies(self):
        effects = ControlledEffects(success_scripts())
        result = collect(UNC_OUT, binding(), effects)
        self.assertTrue(result["accepted"])
        self.assertFalse(result["physical_acceptance"])
        self.assertTrue(result["controlled"])
        self.assertFalse(result["human_review"])
        self.assertEqual(result["actor"], "agent_observed_root_proof")
        self.assertFalse(result["engine_observed_by_collector"])
        self.assertEqual(result["bound_engine_id"], p0.KNOWN_ENGINE_ID)
        self.assertEqual(result["comparison_engine_constant"], p0.KNOWN_ENGINE_ID)
        self.assertNotIn("observed_engine_id", result)
        self.assertFalse(result["changes_distro_default_uid"])
        self.assertEqual(result["ordinary_cd_uid_gid"], [1000, 1000])
        self.assertEqual(result["spawn_count"], 3)
        self.assertEqual(result["commands_attempted"], 3)
        self.assertEqual(effects.spawn_calls, 3)
        self.assertEqual(
            [item["argv"] for item in effects.spawns],
            [p0.fixed_argv(name) for name in p0.COMMAND_ORDER],
        )
        for spawn in effects.spawns:
            self.assertEqual(spawn["env"], p0.fixed_environment())
            self.assertIsInstance(spawn["argv"], list)
        self.assertEqual(effects.terminations, [])
        names = [item["name"] for item in result["commands"]]
        self.assertEqual(names, list(p0.COMMAND_ORDER))
        for command in result["commands"]:
            self.assertEqual(command["returncode"], 0)
            self.assertTrue(command["normal_exit"])
            self.assertTrue(command["eof_stdout"])
            self.assertTrue(command["eof_stderr"])
            self.assertFalse(command["forced_parent_termination"])
            self.assertFalse(command["late"])
            self.assertEqual(command["linux_child_closure"], "normal_wsl_exit_and_eof")
            self.assertFalse(command["parent_termination_proves_linux_child_closure"])
            self.assertNotIn("body", command["stdout"])
            self.assertNotIn(b"0\n", json.dumps(command).encode("utf-8"))
            self.assertTrue(command["stdout"]["persistence"]["completed"])
            self.assertLessEqual(command["deadline"]["cmd_deadline"] - command["deadline"]["cmd_start"], 10.0)
            self.assertLessEqual(command["deadline"]["cmd_deadline"], command["deadline"]["global_deadline"])
        id_path, id_bytes = file_named(effects, "p0-id.stdout.original")
        self.assertEqual(id_bytes, b"0\n")
        self.assertTrue(id_path.startswith(UNC_OUT + "/"))
        self.assertEqual(result["commands"][0]["stdout"]["prefix_sha256"], hashlib.sha256(b"0\n").hexdigest())
        self.assertEqual(result["commands"][0]["stdout"]["retained_bytes"], 2)
        info_path, info_body = file_named(effects, "p0-snapshot-info.stdout.original")
        self.assertEqual(info_body, info_bytes())
        self.assertTrue(info_path.startswith(UNC_OUT + "/"))
        listed, listed_body = file_named(effects, "p0-snapshot-ls.stdout.original")
        self.assertEqual(listed_body, ls_bytes([chain_row()]))
        self.assertTrue(listed.startswith(UNC_OUT + "/"))
        control_path, control_raw = file_named(effects, "p0-control.v1.json")
        control = json.loads(control_raw.decode("utf-8"))
        self.assertLessEqual(len(control_raw), p0.CONTROL_RECORD_CAP)
        self.assertNotIn("write_proof", control)
        self.assertNotIn("accepted", control)
        self.assertNotIn("self_persistence", control)
        self.assertFalse(control["physical_acceptance"])
        self.assertFalse(control["engine_observed_by_collector"])
        self.assertNotIn(p0.CHAIN_ID, json.dumps(control["commands"][1]["stdout"]))
        encoded_streams = json.dumps(control)
        self.assertNotIn("0\\n", encoded_streams)
        self.assertTrue(result["control_record"]["write_proof"]["completed"])
        self.assertTrue(result["control_record"]["write_proof"]["fsync_completed"])
        self.assertTrue(result["control_record"]["write_proof"]["close_completed"])
        self.assertFalse(result["control_record"]["claims_self_persistence"])
        self.assertEqual(len(effects.files), 7)
        self.assertLessEqual(result["allocation"]["preencoding_control_bytes"], p0.CONTROL_RECORD_CAP)
        self.assertLessEqual(result["allocation"]["charged_bytes"], p0.P0_FORMS_CEILING)
        self.assertGreaterEqual(result["allocation"]["charged_bytes"], p0.DIRECTORY_RESERVE + 7 * 4096)
        self.assertTrue(result["allocation"]["within_ceiling"])
        self.assertEqual(effects.events[0], ("mkdir", UNC_OUT))
        id_stdout_reads = [n for index, stream, n in effects.read_requests if index == 0 and stream == "stdout"]
        self.assertTrue(id_stdout_reads)
        self.assertTrue(all(n <= 17 for n in id_stdout_reads))
        self.assertTrue(all(n <= p0.READ_CHUNK for _, _, n in effects.read_requests))
        self.assertTrue(control_path.startswith(UNC_OUT + "/"))

    def test_wrong_uid_chain_listing_and_engine_stop_without_extra_spawns(self):
        uid = ControlledEffects([
            {"stdout": b"1000\n", "stderr": b"", "returncode": 0},
            {"stdout": info_bytes(), "stderr": b"", "returncode": 0},
            {"stdout": ls_bytes([chain_row()]), "stderr": b"", "returncode": 0},
        ])
        uid_result = collect(OUT, binding(), uid)
        self.assertFalse(uid_result["accepted"])
        self.assertEqual(uid.spawn_calls, 1)
        self.assertIn("id_uid_not_zero", uid_result["causes"])
        info = ControlledEffects([
            {"stdout": b"0\n", "stderr": b"", "returncode": 0},
            {"stdout": info_bytes(kind="Active"), "stderr": b"", "returncode": 0},
            {"stdout": ls_bytes([chain_row()]), "stderr": b"", "returncode": 0},
        ])
        info_result = collect(OUT, binding(), info)
        self.assertEqual(info.spawn_calls, 2)
        self.assertIn("snapshot_info_kind_not_committed", info_result["causes"])
        self.assertEqual(
            [item["argv"] for item in info.spawns],
            [p0.fixed_argv("id"), p0.fixed_argv("snapshot_info")],
        )
        listed = ControlledEffects([
            {"stdout": b"0\n", "stderr": b"", "returncode": 0},
            {"stdout": info_bytes(), "stderr": b"", "returncode": 0},
            {"stdout": ls_bytes([("sha256:" + "22" * 32, p0.CHAIN_ID, "Committed"), chain_row(), chain_row()]), "stderr": b"", "returncode": 0},
        ])
        listed_result = collect(OUT, binding(), listed)
        self.assertEqual(listed.spawn_calls, 3)
        self.assertIn("snapshot_ls_chain_row_not_exactly_one", listed_result["causes"])
        self.assertFalse(listed_result["accepted"])
        foreign = ControlledEffects(success_scripts())
        foreign_result = collect(OUT, binding(provenance={"engine_id": FOREIGN_ENGINE}), foreign)
        self.assertEqual(foreign.spawn_calls, 0)
        self.assertEqual(foreign_result["bound_engine_id"], FOREIGN_ENGINE)
        self.assertIn("engine_provenance_mismatch", foreign_result["causes"])
        self.assertFalse(foreign_result["engine_observed_by_collector"])
        absent = binding()
        del absent["provenance"]["engine_id"]
        absent_effects = ControlledEffects(success_scripts())
        absent_result = collect(OUT, absent, absent_effects)
        self.assertIsNone(absent_result["bound_engine_id"])
        self.assertIn("engine_provenance_missing", absent_result["causes"])
        self.assertEqual(absent_effects.spawn_calls, 0)

    def test_deadlines_include_spawn_drain_and_persistence_and_do_not_reset(self):
        slow_spawn = ControlledEffects(success_scripts(), spawn_dt=11.0)
        slow_result = collect(OUT, binding(), slow_spawn)
        self.assertEqual(slow_spawn.spawn_calls, 1)
        self.assertEqual(slow_spawn.terminations, [])
        self.assertFalse(slow_result["accepted"])
        self.assertTrue(slow_result["commands"][0]["late"] or slow_result["commands"][0]["timed_out"])
        self.assertIn("deadline_late", slow_result["causes"])
        inside = ControlledEffects(success_scripts(), spawn_dt=7.0)
        inside_result = collect(OUT, binding(), inside)
        self.assertTrue(inside_result["accepted"])
        self.assertLessEqual(
            inside_result["commands"][0]["timestamps"]["persist_finished"]
            - inside_result["commands"][0]["deadline"]["cmd_start"],
            10.0,
        )
        late_persist = ControlledEffects(success_scripts(), fsync_dt=6.0)
        late_result = collect(OUT, binding(), late_persist)
        self.assertEqual(late_persist.spawn_calls, 1)
        self.assertTrue(late_result["commands"][0]["late"])
        self.assertIn("deadline_late", late_result["causes"])
        persisted = [
            late_result["commands"][0][stream]["persistence"]["completed"]
            for stream in ("stdout", "stderr")
        ]
        self.assertIn(False, persisted)
        global_hit = ControlledEffects([
            {"stdout": b"", "stderr": b"", "returncode": None, "exit_when": "never",
             "stdout_eof": False, "stderr_eof": False, "read_dt": 31.0},
            {"stdout": b"0\n", "stderr": b"", "returncode": 0},
            {"stdout": info_bytes(), "stderr": b"", "returncode": 0},
        ])
        global_result = collect(OUT, binding(), global_hit)
        self.assertEqual(global_hit.spawn_calls, 1)
        self.assertFalse(global_result["accepted"])
        self.assertTrue(global_result["commands"][0]["late"])

    def test_stream_caps_and_combined_stderr_stop_later_commands(self):
        overflow = ControlledEffects([
            {"stdout": b"0\n" + b"x" * 20, "stderr": b"", "returncode": 0},
            {"stdout": info_bytes(), "stderr": b"", "returncode": 0},
            {"stdout": ls_bytes([chain_row()]), "stderr": b"", "returncode": 0},
        ])
        overflow_result = collect(OUT, binding(), overflow)
        self.assertEqual(overflow.spawn_calls, 1)
        self.assertIn("stdout_overflow", overflow_result["causes"])
        self.assertTrue(overflow_result["commands"][0]["stdout"]["remainder_unknown"])
        self.assertEqual(overflow_result["commands"][0]["stdout"]["retained_bytes"], 16)
        id_reads = [n for index, stream, n in overflow.read_requests if index == 0 and stream == "stdout"]
        self.assertEqual(id_reads, [17])
        stderr_scripts = success_scripts()
        stderr_scripts[0]["stderr"] = b"e" * 16384
        stderr_scripts[1]["stderr"] = b"z"
        stderr_fx = ControlledEffects(stderr_scripts)
        stderr_result = collect(OUT, binding(), stderr_fx)
        self.assertEqual(stderr_fx.spawn_calls, 2)
        self.assertIn("stderr_combined_overflow", stderr_result["causes"])
        self.assertTrue(stderr_result["commands"][1]["stderr"]["remainder_unknown"])
        self.assertFalse(stderr_result["accepted"])
        self.assertLessEqual(
            stderr_result["commands"][0]["stderr"]["retained_bytes"]
            + stderr_result["commands"][1]["stderr"]["retained_bytes"],
            16384,
        )

    def test_nonzero_missing_eof_forced_unknown_and_late_block_continuation(self):
        nonzero = ControlledEffects([
            {"stdout": b"0\n", "stderr": b"", "returncode": 1},
            {"stdout": info_bytes(), "stderr": b"", "returncode": 0},
            {"stdout": ls_bytes([chain_row()]), "stderr": b"", "returncode": 0},
        ])
        nonzero_result = collect(OUT, binding(), nonzero)
        self.assertEqual(nonzero.spawn_calls, 1)
        self.assertIn("wsl_status_nonzero", nonzero_result["causes"])
        self.assertEqual(nonzero_result["commands"][0]["linux_child_closure"], "normal_wsl_exit_and_eof")
        missing_eof = ControlledEffects([
            {"stdout": b"0\n", "stderr": b"", "returncode": 0, "stdout_eof": False, "read_dt": 1.0},
            {"stdout": info_bytes(), "stderr": b"", "returncode": 0},
            {"stdout": ls_bytes([chain_row()]), "stderr": b"", "returncode": 0},
        ])
        missing_result = collect(OUT, binding(), missing_eof)
        self.assertEqual(missing_eof.spawn_calls, 1)
        self.assertIn("stream_eof_missing", missing_result["causes"])
        self.assertNotEqual(missing_result["commands"][0]["linux_child_closure"], "normal_wsl_exit_and_eof")
        forced = ControlledEffects([
            {"stdout": b"", "stderr": b"", "returncode": None, "exit_when": "never",
             "stdout_eof": False, "stderr_eof": False, "read_dt": 1.0,
             "code_after_terminate": 0, "eof_after_terminate": True},
            {"stdout": info_bytes(), "stderr": b"", "returncode": 0},
            {"stdout": ls_bytes([chain_row()]), "stderr": b"", "returncode": 0},
        ])
        forced_result = collect(OUT, binding(), forced)
        self.assertEqual(forced.spawn_calls, 1)
        self.assertEqual(forced.terminations, [("owned-parent", 4001)])
        command = forced_result["commands"][0]
        self.assertTrue(command["forced_parent_termination"])
        self.assertEqual(command["linux_child_closure"], "unknown")
        self.assertFalse(command["parent_termination_proves_linux_child_closure"])
        self.assertIn("owned_parent_forced_termination", forced_result["causes"])
        self.assertIn("linux_child_closure_unknown", forced_result["causes"])
        self.assertFalse(forced_result["accepted"])
        unknown = ControlledEffects([
            {"stdout": b"0\n", "stderr": b"", "returncode": None, "exit_when": "never",
             "stdout_eof": True, "stderr_eof": True},
            {"stdout": info_bytes(), "stderr": b"", "returncode": 0},
            {"stdout": ls_bytes([chain_row()]), "stderr": b"", "returncode": 0},
        ])
        unknown_result = collect(OUT, binding(), unknown)
        self.assertEqual(unknown.spawn_calls, 1)
        self.assertIn("wsl_status_unknown", unknown_result["causes"])
        self.assertEqual(unknown_result["commands"][0]["linux_child_closure"], "unknown")

    def test_write_fsync_and_close_failures_keep_unknown_prefix_and_stop(self):
        for flag, cause in (
            ("fail_write", "stream_write_failed"),
            ("fail_fsync", "stream_fsync_failed"),
            ("fail_close", "stream_close_failed"),
        ):
            effects = ControlledEffects(success_scripts(), **{flag: True})
            result = collect(OUT, binding(), effects)
            self.assertEqual(effects.spawn_calls, 1, flag)
            self.assertIn(cause, result["causes"])
            self.assertIn("persisted_prefix_extent_unknown", result["causes"])
            self.assertFalse(result["accepted"])
            self.assertFalse(result["commands"][0]["stdout"]["persistence"]["completed"])
            self.assertTrue(result["commands"][0]["stdout"]["persistence"]["extent_unknown"])
            self.assertLessEqual(effects.spawn_calls, 1)

    def test_directory_refusal_and_controlled_seam_label(self):
        relative = ControlledEffects(success_scripts())
        relative_result = collect("relative/p0", binding(), relative)
        self.assertEqual(relative.spawn_calls, 0)
        self.assertIn("output_dir_not_absolute", relative_result["causes"])
        posix = ControlledEffects(success_scripts())
        posix_result = collect("/tmp/p0", binding(), posix)
        self.assertEqual(posix.spawn_calls, 0)
        self.assertIn("output_dir_not_absolute", posix_result["causes"])
        stale = ControlledEffects(success_scripts(), mkdir_error=FileExistsError(OUT))
        stale_result = collect(OUT, binding(), stale)
        self.assertEqual(stale.spawn_calls, 0)
        self.assertIn("output_dir_not_fresh", stale_result["causes"])
        huge = binding()
        huge["provenance"]["note"] = "n" * 5000
        huge_fx = ControlledEffects(success_scripts())
        huge_result = collect(OUT, huge, huge_fx)
        self.assertEqual(huge_fx.spawn_calls, 0)
        self.assertIn("binding_preencoding_exceeds_control_budget", huge_result["causes"])
        bad = ControlledEffects(success_scripts())
        bad.controlled = False
        with self.assertRaises(p0.P0SeamError):
            collect(OUT, binding(), bad)
        physical = ControlledEffects(success_scripts())
        physical.physical_acceptance = True
        with self.assertRaises(p0.P0SeamError):
            collect(OUT, binding(), physical)
        windows = p0.windows_controlled_effects()
        self.assertTrue(windows.controlled)
        self.assertFalse(windows.physical_acceptance)
        self.assertEqual(windows.label, "controlled")
        self.assertEqual(windows.spawn_calls, 0)


class RegressClock(ControlledEffects):
    """First reading is 10; every later reading is 9."""

    def monotonic(self):
        count = getattr(self, "_reads", 0) + 1
        self._reads = count
        self.t = 10.0 if count == 1 else 9.0
        return self.t


class BoomPoll(ControlledEffects):
    def poll_exit(self, handle):
        raise OSError("poll failed")


class BlockerTests(unittest.TestCase):
    def test_native_classification_and_controlled_spoof_refusal(self):
        signature = inspect.signature(p0.collect_native_p0_v1)
        self.assertEqual(
            list(signature.parameters),
            ["output_dir", "sealed_binding", "reviewed_code_commit"],
        )
        self.assertEqual(
            signature.parameters["reviewed_code_commit"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )
        self.assertNotIn("effects", signature.parameters)
        effects = ControlledEffects(success_scripts())
        self.assertTrue(effects.controlled)
        result = collect_native(OUT, binding(), effects)
        self.assertEqual(result["__factory_calls"], 1)
        self.assertIs(result["controlled"], False)
        self.assertIs(result["physical_acceptance"], False)
        self.assertEqual(result["actor"], "agent_observed_root_proof")
        self.assertIs(result["human_review"], False)
        self.assertIs(result["engine_observed_by_collector"], False)
        self.assertEqual(result["reviewed_code_commit"], COMMIT)
        self.assertIs(result["kernel_preemption_claimed"], False)
        self.assertTrue(result["accepted"])
        _control_path, control_raw = file_named(effects, "p0-control.v1.json")
        self.assertIn(b'"controlled":false', control_raw)
        self.assertNotIn(b'"controlled":true', control_raw)
        control = json.loads(control_raw.decode("utf-8"))
        self.assertIs(control["controlled"], False)
        self.assertEqual(control["reviewed_code_commit"], COMMIT)
        injected = ControlledEffects(success_scripts())
        injected_result = collect(OUT, binding(), injected)
        self.assertIs(injected_result["controlled"], True)
        self.assertIsNone(injected_result["reviewed_code_commit"])
        self.assertIsNone(injected_result["completion_record"])
        spoof = ControlledEffects(success_scripts())
        spoof.claims_native = True
        with self.assertRaises(p0.P0SeamError):
            collect(OUT, binding(), spoof)
        self.assertEqual(spoof.spawn_calls, 0)
        labeled = ControlledEffects(success_scripts())
        labeled.label = "native"
        with self.assertRaises(p0.P0SeamError):
            collect(OUT, binding(), labeled)
        self.assertEqual(labeled.spawn_calls, 0)
        with self.assertRaises(TypeError):
            p0.collect_native_p0_v1(
                OUT, binding(), effects=effects, reviewed_code_commit=COMMIT,
            )

    def test_reviewed_commit_format_refuses_before_mkdir(self):
        for commit in ("A" * 40, "a" * 39, "a" * 41, "g" * 40, None, 40, "a" * 40 + "\n"):
            effects = ControlledEffects(success_scripts())
            result = collect_native(OUT, binding(), effects, commit=commit)
            self.assertEqual(effects.spawn_calls, 0, commit)
            self.assertEqual(result["__factory_calls"], 0, commit)
            self.assertFalse(any(event[0] == "mkdir" for event in effects.events), commit)
            self.assertIn("reviewed_code_commit_invalid", result["causes"], commit)
            self.assertIs(result["controlled"], False)
            self.assertIs(result["physical_acceptance"], False)
            self.assertIsNone(result["reviewed_code_commit"], commit)
            self.assertFalse(result["accepted"])

    def test_clock_starts_before_mkdir_regression_and_late_spawn(self):
        shifted = ControlledEffects(success_scripts(), mkdir_dt=5.0)
        shifted_result = collect(OUT, binding(), shifted)
        self.assertTrue(shifted_result["accepted"])
        self.assertEqual(shifted_result["commands"][0]["deadline"]["global_deadline"], 30.0)
        self.assertEqual(shifted_result["commands"][0]["deadline"]["cmd_start"], 5.0)
        self.assertLessEqual(
            shifted_result["commands"][0]["timestamps"]["persist_finished"],
            30.0,
        )
        past = ControlledEffects(success_scripts(), mkdir_dt=31.0)
        past_result = collect(OUT, binding(), past)
        self.assertEqual(past.spawn_calls, 0)
        self.assertEqual(past.terminations, [])
        self.assertIn("deadline_late", past_result["causes"])
        self.assertIs(past_result["kernel_preemption_claimed"], False)
        self.assertFalse(past_result["accepted"])
        regress = RegressClock(success_scripts())
        regress_result = collect(OUT, binding(), regress)
        self.assertIn("clock_regression", regress_result["causes"])
        self.assertEqual(regress.spawn_calls, 0)
        self.assertEqual(regress.terminations, [])
        self.assertIs(regress_result["kernel_preemption_claimed"], False)
        self.assertFalse(regress_result["accepted"])
        late_spawn = ControlledEffects(success_scripts(), spawn_dt=11.0)
        late_result = collect(OUT, binding(), late_spawn)
        self.assertEqual(late_spawn.terminations, [])
        self.assertEqual(late_result["commands"][0]["linux_child_closure"], "unknown")
        self.assertIs(late_result["kernel_preemption_claimed"], False)
        self.assertIn("deadline_late", late_result["causes"])

    def test_close_crossing_deadline_and_observation_exceptions_keep_facts(self):
        crossed = ControlledEffects(success_scripts(), close_dt=31.0, close_dt_after=6)
        crossed_result = collect(OUT, binding(), crossed)
        proof = crossed_result["control_record"]["write_proof"]
        self.assertFalse(proof["completed"])
        self.assertIsNone(proof["prefix_sha256"])
        self.assertTrue(proof["late"])
        self.assertIn("deadline_late", crossed_result["causes"])
        self.assertIs(crossed_result["kernel_preemption_claimed"], False)
        self.assertFalse(crossed_result["accepted"])
        stream_cross = ControlledEffects(success_scripts(), close_dt=11.0)
        stream_result = collect(OUT, binding(), stream_cross)
        stdout_proof = stream_result["commands"][0]["stdout"]["persistence"]
        self.assertFalse(stdout_proof["completed"])
        self.assertIsNone(stdout_proof["prefix_sha256"])
        self.assertEqual(stream_cross.spawn_calls, 1)
        scripts = success_scripts()
        scripts[0]["stdout_plan"] = [b"0", OSError("read failed")]
        scripts[0]["stderr_plan"] = [b""]
        reading = ControlledEffects(scripts)
        read_result = collect(OUT, binding(), reading)
        self.assertEqual(reading.spawn_calls, 1)
        stdout = read_result["commands"][0]["stdout"]
        self.assertEqual(stdout["retained_bytes"], 1)
        self.assertEqual(stdout["prefix_sha256"], hashlib.sha256(b"0").hexdigest())
        self.assertTrue(stdout["remainder_unknown"])
        self.assertEqual(read_result["commands"][0]["linux_child_closure"], "unknown")
        self.assertIn("stream_read_failed", read_result["causes"])
        self.assertFalse(read_result["accepted"])
        polling = BoomPoll(success_scripts())
        poll_result = collect(OUT, binding(), polling)
        self.assertEqual(polling.spawn_calls, 1)
        self.assertEqual(poll_result["commands"][0]["stdout"]["retained_bytes"], 2)
        self.assertTrue(poll_result["commands"][0]["stdout"]["remainder_unknown"])
        self.assertEqual(poll_result["commands"][0]["linux_child_closure"], "unknown")
        self.assertFalse(poll_result["accepted"])

    def test_native_spawn_refuses_inexact_argv_and_env_without_launch(self):
        launched = []

        async def forbidden(*args, **kwargs):
            launched.append((args, kwargs))
            raise AssertionError("native launch")

        original = p0.asyncio.create_subprocess_exec
        os_name = p0.os.name
        p0.asyncio.create_subprocess_exec = forbidden
        try:
            p0.os.name = "nt"
            windows = p0.windows_controlled_effects()
            self.assertEqual(windows.spawn_calls, 0)
            with self.assertRaises(p0.P0SeamError):
                asyncio.run(windows.spawn(p0.fixed_argv("id"), p0.fixed_environment()))
            self.assertEqual(launched, [])
            native = p0.WindowsNativeP0Effects()
            self.assertEqual(native.spawn_calls, 0)
            self.assertIs(native.controlled, False)
            self.assertIs(native.physical_acceptance, False)
            refusals = [
                p0.fixed_argv("id") + ["--extra"],
                [p0.WSL_EXE],
                [p0.WSL_EXE, "-d", "Ubuntu", "-u", "root", "--cd", "/", "--exec"],
            ]
            user_argv = p0.fixed_argv("id")
            user_argv[4] = "user"
            refusals.append(user_argv)
            for argv in refusals:
                with self.assertRaises(p0.P0SeamError):
                    asyncio.run(native.spawn(argv, p0.fixed_environment()))
            extra_env = p0.fixed_environment()
            extra_env["WSLENV"] = "1"
            hook_env = p0.fixed_environment()
            hook_env["LD_PRELOAD"] = "hook"
            path_env = p0.fixed_environment()
            path_env["PATH"] = "C:/Windows/System32;C:/Windows;C:/extra"
            missing_env = p0.fixed_environment()
            del missing_env["WINDIR"]
            for env in (extra_env, hook_env, path_env, missing_env):
                with self.assertRaises(p0.P0SeamError):
                    asyncio.run(native.spawn(p0.fixed_argv("snapshot_ls"), env))
            p0.os.name = "posix"
            with self.assertRaises(p0.P0SeamError):
                asyncio.run(native.spawn(p0.fixed_argv("id"), p0.fixed_environment()))
            self.assertEqual(native.spawn_calls, 0)
            self.assertEqual(launched, [])
        finally:
            p0.asyncio.create_subprocess_exec = original
            p0.os.name = os_name

    def test_posix_native_entry_does_not_construct_launcher(self):
        os_name = p0.os.name
        p0.os.name = "posix"
        effects = ControlledEffects(success_scripts())
        try:
            result = collect_native(OUT, binding(), effects, native_platform=False)
        finally:
            p0.os.name = os_name
        self.assertEqual(result["__factory_calls"], 0)
        self.assertEqual(effects.spawn_calls, 0)
        self.assertFalse(any(event[0] == "mkdir" for event in effects.events))
        self.assertIn("windows_native_requires_nt", result["causes"])
        self.assertIs(result["controlled"], False)
        self.assertIs(result["physical_acceptance"], False)
        self.assertFalse(result["accepted"])

    def test_completion_is_externally_bound_and_does_not_claim_itself(self):
        effects = ControlledEffects(success_scripts(), mkdir_dt=5.0)
        result = collect_native(UNC_OUT, binding(), effects)
        self.assertTrue(result["accepted"])
        self.assertEqual(len(effects.files), 8)
        names = sorted(path.rsplit("/", 1)[-1] for path in effects.files)
        self.assertEqual(names, sorted([
            "p0-id.stdout.original",
            "p0-id.stderr.original",
            "p0-snapshot-info.stdout.original",
            "p0-snapshot-info.stderr.original",
            "p0-snapshot-ls.stdout.original",
            "p0-snapshot-ls.stderr.original",
            "p0-control.v1.json",
            "p0-completion.v1.json",
        ]))
        _control_path, control_raw = file_named(effects, "p0-control.v1.json")
        _completion_path, completion_raw = file_named(effects, "p0-completion.v1.json")
        self.assertLessEqual(len(control_raw), 8192)
        self.assertLessEqual(len(completion_raw), 4096)
        self.assertLessEqual(len(control_raw) + len(completion_raw), 12288)
        completion = json.loads(completion_raw.decode("utf-8"))
        self.assertEqual(set(completion), {
            "schema", "reviewed_code_commit", "controlled", "physical_acceptance",
            "actor", "human_review", "engine_observed_by_collector", "bound_engine_id",
            "boot_id", "control", "control_write_proof", "predicates_satisfied",
            "causes", "timing", "allocation",
        })
        self.assertEqual(completion["schema"], "gate2-p0-originals.v1")
        self.assertEqual(completion["reviewed_code_commit"], COMMIT)
        self.assertIs(completion["controlled"], False)
        self.assertIs(completion["physical_acceptance"], False)
        self.assertEqual(completion["actor"], "agent_observed_root_proof")
        self.assertIs(completion["human_review"], False)
        self.assertIs(completion["engine_observed_by_collector"], False)
        self.assertEqual(completion["bound_engine_id"], p0.KNOWN_ENGINE_ID)
        self.assertEqual(completion["boot_id"], "boot-extern-001")
        self.assertIs(completion["predicates_satisfied"], True)
        self.assertEqual(completion["causes"], [])
        self.assertEqual(completion["control"], {
            "relative_path": "p0-control.v1.json",
            "size_bytes": len(control_raw),
            "sha256": hashlib.sha256(control_raw).hexdigest(),
        })
        self.assertEqual(completion["control_write_proof"], result["control_record"]["write_proof"])
        self.assertTrue(completion["control_write_proof"]["completed"])
        self.assertEqual(completion["control_write_proof"]["written_bytes"], len(control_raw))
        self.assertEqual(
            completion["control_write_proof"]["prefix_sha256"],
            hashlib.sha256(control_raw).hexdigest(),
        )
        self.assertNotIn("write_proof", completion)
        self.assertNotIn("claims_self_persistence", completion)
        self.assertNotIn("self_persistence", completion)
        completion_sha = hashlib.sha256(completion_raw).hexdigest()
        self.assertNotIn(completion_sha, completion_raw.decode("ascii"))
        descriptor = result["completion_record"]
        self.assertEqual(descriptor["relative_path"], "p0-completion.v1.json")
        self.assertIs(descriptor["claims_self_persistence"], False)
        self.assertTrue(descriptor["write_proof"]["completed"])
        self.assertTrue(descriptor["write_proof"]["fsync_completed"])
        self.assertTrue(descriptor["write_proof"]["close_completed"])
        self.assertEqual(descriptor["write_proof"]["written_bytes"], len(completion_raw))
        self.assertEqual(descriptor["write_proof"]["prefix_sha256"], completion_sha)
        self.assertEqual(descriptor["sha256"], completion_sha)
        self.assertEqual(set(completion["timing"]), {"start", "deadline", "finish"})
        self.assertEqual(completion["timing"]["start"], 0.0)
        self.assertEqual(completion["timing"]["deadline"], 30.0)
        self.assertGreaterEqual(completion["timing"]["finish"], 5.0)
        self.assertLessEqual(completion["timing"]["finish"], 30.0)
        self.assertEqual(set(completion["allocation"]), {
            "ceiling_bytes", "charged_bytes", "within_ceiling", "metadata_copy_bytes",
        })
        self.assertEqual(completion["allocation"]["ceiling_bytes"], p0.P0_FORMS_CEILING)
        self.assertEqual(completion["allocation"]["metadata_copy_bytes"], 12288)
        self.assertLessEqual(completion["allocation"]["charged_bytes"], p0.P0_FORMS_CEILING)
        self.assertIs(completion["allocation"]["within_ceiling"], True)
        late = ControlledEffects(success_scripts(), close_dt=31.0, close_dt_after=7)
        late_result = collect_native(OUT, binding(), late)
        self.assertFalse(late_result["accepted"])
        self.assertFalse(late_result["completion_record"]["write_proof"]["completed"])
        self.assertIsNone(late_result["completion_record"]["write_proof"]["prefix_sha256"])
        self.assertTrue(late_result["control_record"]["write_proof"]["completed"])
        self.assertIs(late_result["kernel_preemption_claimed"], False)

    def test_huge_binding_is_rejected_before_json_and_reserve_precedes_write(self):
        calls = []
        original = p0.json.dumps

        def wrapped(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        nested = binding()
        nested["nested"] = {"level": {"blobs": ["n" * 3000, "m" * 3000]}}
        p0.json.dumps = wrapped
        try:
            sealed = p0.validate_sealed_binding(nested)
        finally:
            p0.json.dumps = original
        self.assertEqual(calls, [])
        self.assertIn("binding_preencoding_exceeds_control_budget", sealed["causes"])
        effects = ControlledEffects(success_scripts())
        result = collect(OUT, binding(), effects)
        reserves = [event for event in effects.events if event[0] == "reserve"]
        opens = [index for index, event in enumerate(effects.events) if event[0] == "open"]
        reserve_indexes = [index for index, event in enumerate(effects.events) if event[0] == "reserve"]
        self.assertEqual(len(reserves), len(opens))
        for reserve_index, open_index in zip(reserve_indexes, opens):
            self.assertLess(reserve_index, open_index)
        self.assertEqual(reserves[0][1], p0.round_up_allocation(2) + p0.INODE_BYTES)
        self.assertEqual(reserves[1][1], p0.round_up_allocation(0) + p0.INODE_BYTES)
        charged = (
            p0.DIRECTORY_RESERVE
            + p0.round_up_allocation(p0.METADATA_COPY_CAP)
            + p0.INODE_BYTES
            + sum(amount for _kind, amount in reserves)
        )
        self.assertEqual(result["allocation"]["charged_bytes"], charged)
        self.assertLessEqual(charged, p0.P0_FORMS_CEILING)
        self.assertGreaterEqual(charged, p0.DIRECTORY_RESERVE + 7 * 4096)
        failed = ControlledEffects(success_scripts(), fail_write=True)
        failed_result = collect(OUT, binding(), failed)
        self.assertIsNone(failed_result["commands"][0]["stdout"]["persistence"]["prefix_sha256"])
        self.assertTrue(any(event[0] == "reserve" for event in failed.events))
        self.assertIn("persisted_prefix_extent_unknown", failed_result["causes"])


class OriginalValidationTests(unittest.TestCase):
    """Temporary files contain controlled bytes, never native evidence."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.directory = self.root / "p0"
        self.directory.mkdir()
        effects = ControlledEffects(success_scripts())
        self.native_return = collect_native(UNC_OUT, binding(), effects)
        self.assertTrue(self.native_return["accepted"])
        self.originals = {}
        for name in tuple(item for pair in p0.STREAM_FILES.values() for item in pair) + (
                p0.CONTROL_NAME, p0.COMPLETION_NAME):
            raw = file_named(effects, name)[1]
            self.originals[name] = raw
            (self.directory / name).write_bytes(raw)
        self.completion = json.loads(self.originals[p0.COMPLETION_NAME])
        self.control = json.loads(self.originals[p0.CONTROL_NAME])

    def descriptor(self, path=None):
        path = self.directory / p0.COMPLETION_NAME if path is None else path
        raw = path.read_bytes()
        return {"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    def validate(self, descriptor=None, **overrides):
        options = {"project_root": self.root, "expected_code_commit": COMMIT,
                   "expected_engine_id": p0.KNOWN_ENGINE_ID, "expected_boot_id": "boot-extern-001"}
        options.update(overrides)
        return p0.validate_p0_originals_v1(self.descriptor() if descriptor is None else descriptor, **options)

    def rewrite(self, *, control=False):
        if control:
            raw = p0.canonical_json(self.control)
            (self.directory / p0.CONTROL_NAME).write_bytes(raw)
            self.completion["control"] = {"relative_path": p0.CONTROL_NAME,
                "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            proof = self.completion["control_write_proof"]
            proof["written_bytes"] = len(raw)
            proof["prefix_sha256"] = hashlib.sha256(raw).hexdigest()
        (self.directory / p0.COMPLETION_NAME).write_bytes(p0.canonical_json(self.completion))

    def restore(self):
        for name, raw in self.originals.items():
            (self.directory / name).write_bytes(raw)
        self.completion = json.loads(self.originals[p0.COMPLETION_NAME])
        self.control = json.loads(self.originals[p0.CONTROL_NAME])

    def test_rereads_fixed_originals_and_keeps_external_completion_proof_separate(self):
        result = self.validate()
        self.assertIs(result["originals_validated"], True)
        self.assertIs(result["physical_acceptance"], False)
        self.assertIs(result["completion_persistence_verified"], False)
        self.assertIs(result["external_native_completion_proof_required"], True)
        self.assertEqual(result["charged_bytes"], self.native_return["allocation"]["charged_bytes"])
        self.assertNotIn("accepted", result)
        # A separately retained return proof exists, but is never passed to or inferred by this validator.
        self.assertTrue(self.native_return["completion_record"]["write_proof"]["completed"])
        self.native_return["completion_record"]["write_proof"]["completed"] = False
        self.assertIs(self.validate()["completion_persistence_verified"], False)

    def test_descriptor_hash_size_root_alias_and_file_type_refusals(self):
        for field, value in (("size_bytes", True), ("size_bytes", 4097), ("sha256", "0" * 64),
                             ("path", str(self.root / "absent")), ("extra", False)):
            with self.subTest(field=field, value=value):
                descriptor = self.descriptor()
                descriptor[field] = value
                with self.assertRaises(ValueError):
                    self.validate(descriptor)
        with self.assertRaises(ValueError):
            self.validate(project_root=self.root / "p0" / "absent")
        outside = self.root.parent / (self.root.name + "-outside")
        outside.write_bytes(self.originals[p0.COMPLETION_NAME])
        self.addCleanup(outside.unlink)
        with self.assertRaises(ValueError):
            self.validate(self.descriptor(outside))
        raw_path = self.directory / p0.STREAM_FILES["id"][0]
        raw_path.unlink()
        raw_path.symlink_to(self.directory / p0.STREAM_FILES["id"][1])
        with self.assertRaises(ValueError):
            self.validate()
        raw_path.unlink()
        raw_path.write_bytes(self.originals[raw_path.name])
        alias = self.root / "alias"
        alias.symlink_to(self.directory, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.validate(self.descriptor(alias / p0.COMPLETION_NAME))
        raw_path.unlink()
        os.link(self.directory / p0.STREAM_FILES["id"][1], raw_path)
        with self.assertRaises(ValueError):
            self.validate()

    def test_native_identity_controlled_and_self_persistence_claims_refuse(self):
        for document, field, value in (
            ("completion", "controlled", True), ("control", "controlled", True),
            ("completion", "physical_acceptance", True), ("control", "physical_acceptance", True),
            ("completion", "reviewed_code_commit", "f" * 40), ("control", "reviewed_code_commit", "f" * 40),
            ("completion", "bound_engine_id", FOREIGN_ENGINE), ("control", "bound_engine_id", FOREIGN_ENGINE),
            ("completion", "boot_id", "other-boot"), ("control", "boot_id", "other-boot"),
            ("completion", "human_review", True), ("control", "engine_observed_by_collector", True),
            ("completion", "actor", "human"), ("completion", "write_proof", {"completed": True}),
            ("control", "claims_self_persistence", True), ("completion", "predicates_satisfied", 1),
            ("completion", "causes", ["deadline_late"]), ("control", "changes_distro_default_uid", True),
            ("control", "provenance_observer", "collector"), ("control", "ordinary_cd_uid_gid", [0, 0]),
        ):
            with self.subTest(document=document, field=field):
                self.restore()
                getattr(self, document)[field] = value
                self.rewrite(control=document == "control")
                with self.assertRaises(ValueError):
                    self.validate()
        self.restore()
        for options in ({"expected_engine_id": FOREIGN_ENGINE}, {"expected_boot_id": "other-boot"},
                        {"expected_code_commit": "A" * 40}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.validate(**options)

    def test_each_status_argv_environment_closure_and_persistence_predicate_refuses(self):
        mutations = [
            ("argv", p0.fixed_argv("id") + ["extra"]), ("env", {**p0.fixed_environment(), "WSLENV": "x"}),
            ("pid", True), ("returncode", False), ("returncode", -15), ("normal_exit", False),
            ("forced_parent_termination", True), ("parent_termination_proves_linux_child_closure", True),
            ("linux_child_closure", "unknown"), ("eof_stdout", False), ("eof_stderr", False),
            ("late", True), ("timed_out", True), ("causes", ["stream_eof_missing"]),
        ]
        for index in range(3):
            for field, value in mutations:
                with self.subTest(index=index, field=field):
                    self.restore()
                    self.control["commands"][index][field] = value
                    self.rewrite(control=True)
                    with self.assertRaises(ValueError):
                        self.validate()
        for stream in ("stdout", "stderr"):
            for field, value in (("eof", False), ("overflow", True), ("remainder_unknown", True),
                                 ("observed_bytes", 123), ("retained_bytes", True), ("cap_bytes", 1),
                                 ("relative_path", "../escape"), ("prefix_sha256", "0" * 64)):
                with self.subTest(stream=stream, field=field):
                    self.restore()
                    self.control["commands"][0][stream][field] = value
                    self.rewrite(control=True)
                    with self.assertRaises(ValueError):
                        self.validate()
            for field, value in (("open_completed", False), ("written_bytes", 123),
                                 ("fsync_completed", False), ("close_completed", False), ("late", True),
                                 ("extent_unknown", True), ("completed", False), ("prefix_sha256", "0" * 64)):
                with self.subTest(stream=stream, persistence=field):
                    self.restore()
                    self.control["commands"][0][stream]["persistence"][field] = value
                    self.rewrite(control=True)
                    with self.assertRaises(ValueError):
                        self.validate()

    def test_control_write_proof_and_all_raw_hashes_are_independently_bound(self):
        for field, value in (("open_completed", False), ("written_bytes", True), ("fsync_completed", False),
                             ("close_completed", False), ("late", True), ("extent_unknown", True),
                             ("completed", False), ("prefix_sha256", "0" * 64)):
            with self.subTest(field=field):
                self.restore()
                self.completion["control_write_proof"][field] = value
                self.rewrite()
                with self.assertRaises(ValueError):
                    self.validate()
        for name in tuple(item for pair in p0.STREAM_FILES.values() for item in pair) + (p0.CONTROL_NAME,):
            with self.subTest(raw=name):
                self.restore()
                (self.directory / name).write_bytes(self.originals[name] + b"x")
                with self.assertRaises(ValueError):
                    self.validate()

    def test_time_order_and_allocation_semantics_refuse(self):
        changes = [
            ("timing", "start", -1), ("timing", "deadline", 31.0), ("timing", "finish", 31.0),
            ("timing", "finish", True), ("allocation", "ceiling_bytes", p0.P0_FORMS_CEILING + 1),
            ("allocation", "metadata_copy_bytes", 0), ("allocation", "charged_bytes", 1),
            ("allocation", "within_ceiling", False),
            ("timing", "finish", 10 ** 1000),
        ]
        for group, field, value in changes:
            with self.subTest(group=group, field=field):
                self.restore()
                self.completion[group][field] = value
                self.rewrite()
                with self.assertRaises(ValueError):
                    self.validate()
        for group, field, value in (("deadline", "cmd_deadline", 11.0), ("deadline", "capture_deadline", 9.0),
                                    ("deadline", "cmd_start", -1.0), ("timestamps", "spawn_returned", -1.0),
                                    ("timestamps", "drain_finished", 11.0), ("timestamps", "persist_finished", 11.0)):
            with self.subTest(group=group, field=field):
                self.restore()
                self.control["commands"][0][group][field] = value
                self.rewrite(control=True)
                with self.assertRaises(ValueError):
                    self.validate()

    def test_reread_semantics_refuse_even_when_raw_and_control_hashes_are_rebound(self):
        for index, body in ((0, b"1000\n"), (1, info_bytes(name=PARENT)),
                            (2, ls_bytes([(p0.CHAIN_ID, PARENT, "Active")]))):
            with self.subTest(index=index):
                self.restore()
                stream = self.control["commands"][index]["stdout"]
                (self.directory / stream["relative_path"]).write_bytes(body)
                stream.update(retained_bytes=len(body), observed_bytes=len(body), prefix_sha256=hashlib.sha256(body).hexdigest())
                stream["persistence"].update(written_bytes=len(body), prefix_sha256=hashlib.sha256(body).hexdigest())
                self.rewrite(control=True)
                with self.assertRaises(ValueError):
                    self.validate()

    def test_all_stream_caps_and_rounded_all_forms_ceiling_accept_exact_maxima(self):
        scripts = success_scripts()
        info = {"Name": p0.CHAIN_ID, "Kind": "Committed", "Padding": ""}
        info["Padding"] = "x" * (p0.STDOUT_CAPS["snapshot_info"] - len(p0.canonical_json(info)))
        scripts[1]["stdout"] = p0.canonical_json(info)
        listing = ls_bytes([chain_row()])
        scripts[2]["stdout"] = listing + b"x" * (p0.STDOUT_CAPS["snapshot_ls"] - len(listing) - len(b" Committed\n")) + b" Committed\n"
        for item, size in zip(scripts, (4097, 4097, 8190)):
            item["stderr"] = b"e" * size
        effects = ControlledEffects(scripts)
        returned = collect_native(UNC_OUT, binding(), effects)
        self.assertTrue(returned["accepted"])
        for name in self.originals:
            (self.directory / name).write_bytes(file_named(effects, name)[1])
        result = self.validate()
        self.assertEqual(result["charged_bytes"], p0.maximum_inclusive_charge())
        self.assertLessEqual(result["charged_bytes"], p0.P0_FORMS_CEILING)
        control = json.loads(file_named(effects, p0.CONTROL_NAME)[1])
        self.assertEqual([row["stderr"]["cap_bytes"] for row in control["commands"]], [16384, 12287, 8190])

    def test_duplicate_nonfinite_noncanonical_and_oversize_metadata_refuse(self):
        bad_completion = [self.originals[p0.COMPLETION_NAME].replace(b'"controlled":false',
                          b'"controlled":true,"controlled":false'),
                          b'{"extra":NaN}', b'{"extra":1e999}', b" " + self.originals[p0.COMPLETION_NAME], b"x" * 4097]
        for raw in bad_completion:
            with self.subTest(raw=raw[:40]):
                self.restore()
                (self.directory / p0.COMPLETION_NAME).write_bytes(raw)
                with self.assertRaises(ValueError):
                    self.validate()
        self.restore()
        raw = self.originals[p0.CONTROL_NAME].replace(b'"controlled":false', b'"controlled":true,"controlled":false')
        (self.directory / p0.CONTROL_NAME).write_bytes(raw)
        self.completion["control"]["size_bytes"] = len(raw)
        self.completion["control"]["sha256"] = hashlib.sha256(raw).hexdigest()
        self.rewrite()
        with self.assertRaises(ValueError):
            self.validate()

    def test_exact_eight_original_inventory_refuses_extra_forms_with_bounded_scan(self):
        extra = self.directory / "extra.original"
        extra.write_bytes(b"x")
        original_scandir = p0.os.scandir
        calls = []
        class TrackedScan:
            def __init__(self, path):
                self.rows = original_scandir(path)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.rows.close()
            def __iter__(self):
                return self
            def __next__(self):
                row = next(self.rows)
                calls.append(row.name)
                if len(calls) > 9:
                    raise AssertionError("P0 inventory exceeded nine entries")
                return row
        with patch.object(p0.os, "scandir", TrackedScan), self.assertRaises(ValueError):
            self.validate()
        self.assertGreater(len(calls), 0)
        self.assertLessEqual(len(calls), 9)
        extra.unlink()
        extra.mkdir()
        with self.assertRaises(ValueError):
            self.validate()

    def test_actual_block_allocation_and_unknown_blocks_refuse(self):
        original_lstat, original_fstat = Path.lstat, p0.os.fstat
        for target in (self.directory, self.directory / p0.STREAM_FILES["id"][1]):
            target_info = target.lstat()
            identity = (target_info.st_dev, target_info.st_ino)
            for blocks in (p0.P0_FORMS_CEILING // 512 + 1, None, -1, True):
                with self.subTest(target=target.name, blocks=blocks):
                    def alter(info):
                        if (info.st_dev, info.st_ino) != identity:
                            return info
                        fields = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
                        fields["st_blocks"] = blocks
                        return SimpleNamespace(**fields)
                    def fake_lstat(path, *args, **kwargs):
                        return alter(original_lstat(path, *args, **kwargs))
                    def fake_fstat(fd):
                        return alter(original_fstat(fd))
                    with patch.object(Path, "lstat", fake_lstat), patch.object(p0.os, "fstat", fake_fstat), \
                            self.assertRaises(ValueError):
                        self.validate()


class AdditionalNativeBoundaryTests(unittest.TestCase):
    def test_duplicate_and_nonfinite_snapshot_json_refuses(self):
        valid = info_bytes().rstrip()
        malformed = [valid[:-1] + b',"Name":"' + p0.CHAIN_ID.encode() + b'"}',
                     valid[:-1] + b',"unused":NaN}', valid[:-1] + b',"unused":Infinity}',
                     valid[:-1] + b',"unused":-Infinity}', valid[:-1] + b',"unused":1e999}',
                     valid[:-1] + b',"unused":{"k":1,"k":2}}']
        for raw in malformed:
            with self.subTest(raw=raw):
                self.assertFalse(p0.validate_snapshot_info(raw)["ok"])

    def test_completion_cap_refuses_before_exclusive_open(self):
        original = p0._completion_document
        def oversized(*args, **kwargs):
            record = original(*args, **kwargs)
            record["oversized"] = "x" * p0.COMPLETION_RECORD_CAP
            return record
        effects = ControlledEffects(success_scripts())
        with patch.object(p0, "_completion_document", oversized):
            result = collect_native(OUT, binding(), effects)
        self.assertFalse(result["accepted"])
        self.assertIn("control_record_preencoding_exceeded", result["causes"])
        self.assertFalse(any(path.endswith(p0.COMPLETION_NAME) for path in effects.opened))
        self.assertIsNone(result["completion_record"])
        self.assertEqual(len(effects.files), 7)

    def test_native_deadline_starts_before_factory_and_sync_event_loop_startup(self):
        for stage in ("factory", "event_loop", "async_factory"):
            with self.subTest(stage=stage):
                effects = ControlledEffects(success_scripts())
                if stage == "factory":
                    result = collect_native(OUT, binding(), effects, factory_dt=31.0)
                elif stage == "event_loop":
                    original = p0.asyncio.run
                    def delayed(coroutine):
                        effects.t += 31.0
                        return original(coroutine)
                    with patch.object(p0.asyncio, "run", delayed):
                        result = collect_native(OUT, binding(), effects)
                else:
                    def factory():
                        effects.t += 31.0
                        return effects
                    with patch.object(p0.os, "name", "nt"), patch.object(p0.time, "monotonic", effects.monotonic), \
                            patch.object(p0, "windows_native_p0_effects", factory):
                        result = asyncio.run(p0.collect_native_p0_v1_async(OUT, binding(), reviewed_code_commit=COMMIT))
                self.assertFalse(result["accepted"])
                self.assertIn("deadline_late", result["causes"])
                self.assertEqual(effects.spawn_calls, 0)
                self.assertEqual(effects.files, {})
                self.assertFalse(any(event[0] == "mkdir" for event in effects.events))


if __name__ == "__main__":
    unittest.main()
