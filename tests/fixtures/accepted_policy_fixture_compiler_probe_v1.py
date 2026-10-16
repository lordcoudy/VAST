"""2.10 host probe runner for stages B1-B3 of the component admission plan.

It refuses BEFORE create on any pre-run guard drift (P0 committed snapshot,
engine/provider identity, capacity, container list, GPU). After create it
RECORDS and never enforces: effective config, live mounts/cgroup facts, the
probe export, containment and closure. It never calls the 2.9 owner, never
accepts an ELF and grants no qualification by itself; gate 2 reviews its
originals. Docker effects go only through the 2.9 fixed client/attach.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import time
from typing import Any, Callable, Iterable, Mapping

from tests.fixtures import accepted_policy_fixture_compiler_component_v1 as component
from tests.fixtures import accepted_policy_fixture_compiler_v1 as compiler

PROGRAM_RELATIVE = "tests/fixtures/accepted_policy_fixture_compiler_probe_program_v1.py"
PROBES = ("B1", "B2", "B3")
DEADLINE_NS = 150_000_000_000
PRESTART_NS, WORK_NS, CLOSE_NS = 10_000_000_000, 60_000_000_000, 10_000_000_000
TERM_NS, KILL_NS, FINAL_NS = 30_000_000_000, 30_000_000_000, 10_000_000_000
RECORD_LIMIT = 1048576
P0_LIMIT = 65536

# Pinned pre-run identity (plan V5 section 1; raw replies in observations-01).
EXPECTED = {
    "engine_id": "1e493309-3767-45fb-9078-05b838bdfd80",
    "server_version": "29.7.2",
    "kernel": "6.6.87.2-microsoft-standard-WSL2",
    "security_options": ["name=seccomp,profile=builtin", "name=cgroupns"],
    "runtimes_sha256": "b480bc9619d585079ca9926e520ee190fc971f2e7c2c6c01b5256ac058c4a5d1",
    "provider_size": 10469582904,
    "rootfs_sha256": "1e0fe0c49e48962dc125b19e5b1936c564f1c6a3e00006d5e5cca7dc7ebfd981",
    "env_keys_sha256": "6785bc7c38e52df3c99c3856d0619875fc1a1f44aab077baa550da820b8f1db9",
    "platform_manifest": compiler.PROVIDER_PLATFORM_MANIFEST,
    "unpacked_bytes": 18930790400,
    "chain_id": "sha256:583abc9004877e79fd0f5d47e4c7cff085b8538fdcbff0c070e044bdb0b43c1a",
}


class ProbeRefusal(RuntimeError):
    """Refused before any container create; carries the recorded facts."""

    def __init__(self, cause: str, facts: Mapping[str, Any]) -> None:
        super().__init__(cause)
        self.cause, self.facts = cause, facts


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _c_free_bytes() -> int:
    row = os.statvfs("/mnt/c")  # the reading _compiler_floor_facts_v1 compares
    return row.f_bavail * row.f_frsize


def _gpu_processes() -> list[str] | None:
    try:
        run = subprocess.run(["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
                             capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if run.returncode != 0 or len(run.stdout) > 4096:
        return None
    return [line.strip() for line in run.stdout.decode("ascii", "replace").splitlines() if line.strip()]


def p0_committed(raw: bytes) -> bool:
    """`ctr -n moby snapshots --snapshotter overlayfs info <chain>` must show this chain Committed."""
    try:
        value = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError):
        return False
    return type(value) is dict and value.get("Name") == EXPECTED["chain_id"] and value.get("Kind") == "Committed"


def probe_request_v1(probe: str, sources: Mapping[str, bytes]) -> bytes:
    header = {"probe": probe, "sources": {name: {"size_bytes": len(raw), "sha256": _sha(raw)}
                                          for name, raw in sorted(sources.items())}}
    encoded = component.canonical_json_v1(header)
    return (b"VASTPB1\n" + struct.pack("!I", len(encoded)) + encoded
            + b"".join(raw for _, raw in sorted(sources.items())))


def config_diff(requested: Mapping[str, Any], actual: Mapping[str, Any]) -> list[list[Any]]:
    """Record-only: every requested key whose effective value differs."""
    rows = []
    config, host = actual.get("Config") or {}, actual.get("HostConfig") or {}
    for key, value in sorted(requested.items()):
        if key == "HostConfig":
            for host_key, host_value in sorted(value.items()):
                if host.get(host_key) != host_value:
                    rows.append(["HostConfig." + host_key, host_value, host.get(host_key)])
        elif key != "Image" and config.get(key) != value:
            rows.append([key, value, config.get(key)])
    return rows


def _measure() -> dict[str, Any]:
    """Non-root disk/journal measurements (plan section 5), recorded before and after each run."""
    row: dict[str, Any] = {"c_free_bytes": _c_free_bytes()}
    try:
        root = os.statvfs("/")
        row["ext4_used_bytes"] = (root.f_blocks - root.f_bfree) * root.f_frsize
    except OSError as error:
        row["ext4_used_bytes"] = {"unavailable": type(error).__name__}
    try:
        run = subprocess.run(["journalctl", "--disk-usage"], capture_output=True, timeout=10, check=False)
        row["journal"] = run.stdout[:512].decode("ascii", "replace").strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        row["journal"] = {"unavailable": type(error).__name__}
    return row


def run_probe_container_v1(*, project_root: Path, probe: str, output_dir: Path, p0_path: Path,
                           allowed_prior_cids: Iterable[str] = (), absolute_deadline_ns: int | None = None,
                           clock: Callable[[], int] = time.monotonic_ns) -> dict[str, Any]:
    """Run one fixed probe container under the plan's guards; record everything after create."""
    if probe not in PROBES:
        raise ValueError("unknown probe")
    root = Path(project_root)
    if not root.is_absolute() or root.resolve(strict=True) != root:
        raise ValueError("probe project root")
    output = compiler._compiler_physical_v1(output_dir, root, fresh=True)
    output.mkdir(mode=0o700)
    facts: dict[str, Any] = {"probe": probe, "causes": [], "guards": {}, "cid": None, "created": False,
                             "start_attempted": False, "export": None, "containment": [], "final_state": None,
                             "config_diff": None, "live": None, "closure": None, "accepted": False}
    causes = facts["causes"]

    def fail(code: str) -> None:
        if code not in causes:
            causes.append(code)

    def record(name: str, value: Any) -> None:
        raw = component.canonical_json_v1(value)
        if len(raw) > RECORD_LIMIT:
            raw = component.canonical_json_v1({"record_bound_exceeded": len(raw), "sha256": _sha(raw)})
        fd = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            if os.write(fd, raw) != len(raw):
                raise OSError("short record write")
            os.fsync(fd)
        finally:
            os.close(fd)

    def refuse(code: str) -> None:
        fail(code)
        record("probe.refusal.original.json", facts)
        raise ProbeRefusal(code, facts)

    # --- Local pre-run guards: before the clock starts and before any container exists. ---
    p0 = compiler._compiler_physical_v1(p0_path, root)
    p0_raw = compiler._compiler_read_v1(p0, P0_LIMIT)
    facts["guards"]["p0_sha256"] = _sha(p0_raw)
    if not p0_committed(p0_raw):
        refuse("probe_p0_not_committed")
    program = compiler._compiler_physical_v1(root / PROGRAM_RELATIVE, root)
    program_raw = compiler._compiler_read_v1(program, 262144)
    profile_raw = compiler._compiler_read_v1(root / "tests/fixtures/accepted_policy_fixture_compiler_seccomp_v1.json", 65536)
    sources = {name: component.component_source_v1(name) for name in component._BUILDERS} if probe == "B1" else {}
    request = probe_request_v1(probe, sources)
    facts["guards"].update(program_sha256=_sha(program_raw), request_sha256=_sha(request),
                           request_bytes=len(request))
    c_free = _c_free_bytes()
    facts["guards"]["c_free_bytes"] = c_free
    if c_free < component.C_BYTES + component.ADDITIONAL_DISK_UPPER_BYTES:
        refuse("probe_capacity_floor")
    gpu = _gpu_processes()
    facts["guards"]["gpu_processes"] = gpu
    if gpu is None or gpu:
        refuse("probe_gpu_unavailable_or_busy")
    facts["measure_before"] = _measure()

    start = clock()
    deadline = start + DEADLINE_NS if absolute_deadline_ns is None else min(start + DEADLINE_NS, absolute_deadline_ns)
    client = compiler._DockerClientV1(output, deadline)
    prestart_end = min(start + PRESTART_NS, deadline - (CLOSE_NS + TERM_NS + KILL_NS + FINAL_NS))

    def rpc(method, path, body=None, *, phase, cleanup=False, upgrade=False):
        current = clock()
        until = min(phase, deadline, current + (30_000_000_000 if "/wait?" in path else 10_000_000_000))
        if not current < until:
            raise compiler.FixtureCompilerError("probe_phase_deadline")
        return client.request(method, path, body, deadline_ns=until, cleanup=cleanup, upgrade=upgrade)

    # --- API pre-run guards: still before create. ---
    try:
        version = rpc("GET", "/version", phase=prestart_end)
        info = rpc("GET", "/info", phase=prestart_end)
        image = rpc("GET", "/images/" + compiler.PROVIDER_ID + "/json?manifests=1", phase=prestart_end)
        listed = rpc("GET", "/containers/json?all=1", phase=prestart_end)
    except compiler.FixtureCompilerError as error:
        for code in error.causes:
            fail(code)
        refuse("probe_guard_api")
    manifests = [row for row in (image.get("Manifests") or []) if type(row) is dict] if type(image) is dict else []
    amd64 = [row for row in manifests if row.get("ID") == EXPECTED["platform_manifest"]]
    keys = sorted(entry.split("=", 1)[0] for entry in ((image.get("Config") or {}).get("Env") or [])) if type(image) is dict else []
    observed = {
        "engine_id": info.get("ID") if type(info) is dict else None,
        "server_version": version.get("Version") if type(version) is dict else None,
        "kernel": info.get("KernelVersion") if type(info) is dict else None,
        "security_options": info.get("SecurityOptions") if type(info) is dict else None,
        "runtimes_sha256": _sha(component.canonical_json_v1(info.get("Runtimes"))) if type(info) is dict else None,
        "provider_size": image.get("Size") if type(image) is dict else None,
        "rootfs_sha256": _sha(component.canonical_json_v1(image.get("RootFS"))) if type(image) is dict else None,
        "env_keys_sha256": _sha(component.canonical_json_v1(keys)),
        "platform_manifest": amd64[0].get("ID") if len(amd64) == 1 else None,
        "unpacked_bytes": ((amd64[0].get("ImageData") or {}).get("Size") or {}).get("Unpacked")
        if len(amd64) == 1 and amd64[0].get("Available") is True else None,
        "chain_id": EXPECTED["chain_id"] if p0_committed(p0_raw) else None,
    }
    facts["guards"]["identity"] = observed
    drift = sorted(key for key in EXPECTED if observed.get(key) != EXPECTED[key])
    if type(image) is not dict or image.get("Id") != compiler.PROVIDER_ID:
        drift.append("provider_id")
    if type(image) is dict and image.get("RepoDigests") != [compiler.PROVIDER]:
        drift.append("repo_digests")
    if type(image) is dict and (image.get("Config") or {}).get("Volumes") not in (None, {}):
        drift.append("volumes")
    if drift:
        facts["guards"]["identity_drift"] = drift
        refuse("probe_identity_drift")
    allowed = set(allowed_prior_cids)
    rows = listed if type(listed) is list else []
    facts["guards"]["containers"] = [[row.get("Id"), row.get("State")] for row in rows if type(row) is dict]
    if (type(listed) is not list or {row.get("Id") for row in rows if type(row) is dict} != allowed
            or any(type(row) is not dict or row.get("State") == "running" for row in rows)):
        refuse("probe_container_list")

    # --- After create: record, never enforce; contain on ANY failure. ---
    nonce = os.urandom(16).hex()
    name = "vast-fixture-compiler-probe-" + probe.lower() + "-" + nonce
    config = compiler.compiler_container_config_v1(image, environment_keys=keys, publisher_path=str(program),
                                                   profile_raw=profile_raw, nonce=nonce, source_sha256=_sha(request))
    record("probe.intent.original.json", {"name": name, "nonce": nonce, "probe": probe, "deadline_ns": deadline,
                                          "request_sha256": _sha(request), "config_sha256": _sha(component.canonical_json_v1(config))})
    received, previous = [None], []
    interrupt: BaseException | None = None
    attach = None
    compiler._compiler_install_handlers_v1(received, previous)
    try:
        try:
            try:
                created = rpc("POST", "/containers/create?name=" + name, config, phase=prestart_end)
            except compiler.FixtureCompilerError:
                # A lost create reply never authorizes a duplicate: reconcile by exact name.
                found = rpc("GET", "/containers/json?all=1&filters=" + compiler.quote(
                    component.canonical_json_v1({"name": ["^/" + name + "$"]}).decode("ascii"), safe=""),
                    phase=prestart_end, cleanup=True)
                facts["create_reconciled"] = [row.get("Id") for row in found if type(row) is dict] if type(found) is list else None
                raise
            cid = created.get("Id") if type(created) is dict else None
            if type(cid) is not str or re.fullmatch("[0-9a-f]{64}", cid) is None:
                raise compiler.FixtureCompilerError("probe_create_reply")
            facts["cid"], facts["created"] = cid, True
            record("probe.cid.original.json", {"cid": cid, "name": name})
            duplex = rpc("POST", "/containers/" + cid + "/attach?stream=1&stdin=1&stdout=1&stderr=1",
                         phase=prestart_end, upgrade=True)
            attach = compiler._CompilerAttachV1(duplex, output)
            facts["start_attempted"] = True
            rpc("POST", "/containers/" + cid + "/start", phase=prestart_end)
            started_at = clock()
            work_end = min(started_at + WORK_NS, deadline - (CLOSE_NS + TERM_NS + KILL_NS + FINAL_NS))
            duplex.arm_data_deadline(work_end)
            live = rpc("GET", "/containers/" + cid + "/json", phase=work_end)
            pid = ((live or {}).get("State") or {}).get("Pid") if type(live) is dict else None
            try:
                facts["live"] = compiler._compiler_process_facts_v1(pid, cid)
            except Exception as error:
                facts["live"] = {"unavailable": type(error).__name__, "pid": pid}
            try:
                facts["live_mountinfo"] = compiler._compiler_proc_read_v1("/proc/%d/mountinfo" % pid, 65536).decode("ascii", "replace")
            except Exception as error:
                facts["live_mountinfo"] = {"unavailable": type(error).__name__}
            attach.sendall(request)
            attach.shutdown_write()
            facts["export"] = compiler.capture_export_v1(attach.read, output)
        except BaseException as error:  # noqa: B036 - record, contain, then re-raise interrupts
            for code in (error.causes if isinstance(error, compiler.FixtureCompilerError) else ["probe_" + type(error).__name__]):
                fail(code)
            if isinstance(error, compiler.FixtureCompilerError) and hasattr(error, "facts"):
                facts["failed_operation"] = error.facts
            if not isinstance(error, Exception):
                interrupt = error
        finally:
            if attach is not None:
                try:
                    attach.close()
                except BaseException as error:  # noqa: B036
                    for code in (error.causes if isinstance(error, compiler.FixtureCompilerError) else ["probe_attach_" + type(error).__name__]):
                        fail(code)
                facts["attach"] = attach.facts
        cid = facts["cid"]
        if cid is not None and facts["start_attempted"]:
            def contain_step(label, method, path, phase):
                nonlocal interrupt
                try:
                    reply = rpc(method, path, phase=phase, cleanup=True)
                    facts["containment"].append([label, "reply", reply if type(reply) in (dict, type(None)) else str(reply)])
                    return reply
                except BaseException as error:  # noqa: B036
                    codes = list(error.causes) if isinstance(error, compiler.FixtureCompilerError) else ["probe_" + type(error).__name__]
                    facts["containment"].append([label, "causes", codes])
                    for code in codes:
                        fail(code)
                    if not isinstance(error, Exception) and interrupt is None:
                        interrupt = error
                    return None
            now = clock()
            close_end = min(now + CLOSE_NS, deadline - (TERM_NS + KILL_NS + FINAL_NS))
            reply = contain_step("normal_close_wait", "POST", "/containers/" + cid + "/wait?condition=not-running",
                                 close_end) if close_end > now else None
            stopped = type(reply) is dict and type(reply.get("StatusCode")) is int
            for signo, grace in (("SIGTERM", TERM_NS), ("SIGKILL", KILL_NS)):
                if stopped:
                    break
                end = min(clock() + grace, deadline - FINAL_NS)
                contain_step("kill_" + signo, "POST", "/containers/" + cid + "/kill?signal=" + signo, end)
                reply = contain_step("wait_after_" + signo, "POST", "/containers/" + cid + "/wait?condition=not-running", end)
                stopped = type(reply) is dict and type(reply.get("StatusCode")) is int
            final = contain_step("final_inspect", "GET", "/containers/" + cid + "/json?size=1", deadline)
            if type(final) is dict:
                facts["final_state"] = final.get("State")
                facts["config_diff"] = config_diff(config, final)
                facts["container_size"] = {"SizeRw": final.get("SizeRw"), "SizeRootFs": final.get("SizeRootFs")}
            if type(facts.get("live")) is dict and "cgroup_path" in facts["live"]:
                try:
                    facts["closure"] = compiler._compiler_closed_facts_v1(facts["live"], cid)
                except Exception as error:
                    facts["closure"] = {"unavailable": type(error).__name__}
    finally:
        for code in compiler._compiler_restore_handlers_v1(previous):
            fail(code)
        if received[0] is not None:
            fail(received[0].replace("owner_", "probe_"))
        try:
            facts["measure_after"] = _measure()
        except Exception as error:
            facts["measure_after"] = {"unavailable": type(error).__name__}
        facts["rpc"] = {"attempts": client.facts["attempts"], "metadata_bytes": client.facts["metadata_bytes"],
                        "causes": list(client.causes)}
        record("probe.result.original.json", facts)
    if interrupt is not None:
        raise interrupt
    return facts
