"""Portable test setup only: real ELF, no Docker or qualification authority.

Only the three existing small positive custody/probe tests use this explicit
context. Genuine fixtures never select it or fall back to it. Local execution
needs a separate reservation for the tmpfs/RAM/swap and retained copies; the
initial B2 local preparatory allowance deliberately excludes these three tests.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch

from tests.fixtures import accepted_policy_fixture_compiler_v1 as compiler
from tests.fixtures.accepted_policy_standalone_reader_fixture_v2 import (
    _bounded_json_v2, _capture_owned_reader_v2, _write_result_v2,
)


@contextmanager
def controlled_fixture_compiler_v1(project_root):
    """Double only compiler authority; custody/default readers remain actual."""
    root = Path(project_root).resolve(strict=True)
    bindings, workspaces = {}, []
    authority = {"compiler_qualification": {"controlled_test_only": "qualification"},
                 "compiler_admission": {"controlled_test_only": "admission"}}
    import time
    authority["compiler_absolute_deadline_ns"] = time.monotonic_ns() + 150_000_000_000

    def preflight(**kwargs):
        if (kwargs["qualification"] is not authority["compiler_qualification"]
                or kwargs["admission"] is not authority["compiler_admission"]
                or kwargs["absolute_deadline_ns"] != authority["compiler_absolute_deadline_ns"]):
            raise AssertionError("controlled compiler authority/deadline was not forwarded unchanged")
        raw = kwargs["source_bytes"]
        if type(raw) is not bytes or not 0 < len(raw) <= 65536:
            raise AssertionError("controlled positive source exceeds 64 KiB")
        key = (Path(kwargs["source_path"]), Path(kwargs["executable_path"]))
        binding = (len(raw), hashlib.sha256(raw).hexdigest())
        if key in bindings and bindings[key] != binding:
            raise AssertionError("controlled prospective source drifted")
        bindings[key] = binding

    def compile_external(**kwargs):
        source, executable = Path(kwargs["source_path"]), Path(kwargs["executable_path"])
        raw = compiler._compiler_read_v1(source, 65536)
        preflight(**kwargs, source_bytes=raw)
        if (not source.is_relative_to(root) or not executable.is_relative_to(root)
                or executable.exists() or bindings[(source, executable)] != (len(raw), hashlib.sha256(raw).hexdigest())):
            raise AssertionError("controlled compiler input/output binding differs")
        compiler._compiler_preparation_clock_v1(kwargs["absolute_deadline_ns"])
        with open("/proc/self/mountinfo", "rb") as stream:
            mounts = stream.read(262145)
        if len(mounts) > 262144:
            raise AssertionError("controlled tmpfs mount inventory exceeds bound")
        rows = [line.split() for line in mounts.splitlines() if len(line.split()) > 6 and line.split()[4] == b"/dev/shm"]
        usage = os.statvfs("/dev/shm")
        if (len(rows) != 1 or rows[0][rows[0].index(b"-") + 1] != b"tmpfs"
                or not 0 < usage.f_blocks * usage.f_frsize <= 32 * 1024**3
                or usage.f_bavail * usage.f_frsize < 16 * 1024**2):
            raise AssertionError("controlled compiler requires the declared finite existing tmpfs")
        compiler._compiler_preparation_clock_v1(kwargs["absolute_deadline_ns"])
        workspace = Path(tempfile.mkdtemp(prefix="vast-controlled-cc-", dir="/dev/shm"))
        workspaces.append(workspace)
        compiler._compiler_preparation_clock_v1(kwargs["absolute_deadline_ns"])
        with (workspace / "engine.c").open("xb") as stream:
            if stream.write(raw) != len(raw):
                raise AssertionError("controlled source copy was short")
            stream.flush()
            os.fsync(stream.fileno())
        compiler._compiler_preparation_clock_v1(kwargs["absolute_deadline_ns"])
        command = ["/usr/bin/env", "-i", "PATH=/usr/bin:/bin", "LC_ALL=C", "HOME=" + str(workspace),
            "TMPDIR=" + str(workspace), "TMP=" + str(workspace), "TEMP=" + str(workspace),
            "/usr/bin/prlimit", "--as=134217728", "--fsize=1048576", "--core=1", "--cpu=10", "--",
            "/usr/bin/cc", "-O0", "-std=c11", "-fno-lto", str(workspace / "engine.c"), "-o", str(workspace / "engine")]
        facts, _, _ = _capture_owned_reader_v2(command=command, cwd=workspace,
            outputs={name: workspace / (name + ".original") for name in ("stdout", "stderr")},
            deadline={"absolute_monotonic_ns": kwargs["absolute_deadline_ns"], "term_grace_ns": 5_000_000_000,
                      "kill_grace_ns": 5_000_000_000, "final_ns": 5_000_000_000})
        result_raw = _bounded_json_v2({"controlled_test_only": True, "capture": facts}, 32767)
        persistence = None
        if result_raw is not None:
            persistence = _write_result_v2(workspace / "capture.result.original.json", result_raw + b"\n",
                                          kwargs["absolute_deadline_ns"])
        complete_result = (persistence is not None and not persistence["causes"]
                           and persistence["written_bytes"] == len(result_raw) + 1)
        if (not complete_result or facts["causes"] or facts["returncode"] != 0 or facts["forced"] or facts["signal"] is not None
                or not facts["closure"]["closed"] or any(not facts[name]["eof"] or facts[name]["remainder_unknown"]
                or not facts[name]["file"]["fsync_completed"] or not facts[name]["file"]["close_completed"]
                for name in ("stdout", "stderr"))):
            status = _bounded_json_v2({"controlled_test_only": True, "originals": str(workspace),
                "capture": facts, "result_bound": result_raw is not None,
                "result_persistence": persistence}, 65536)
            raise AssertionError("controlled compiler refused: " + (status.decode("ascii") if status is not None
                else "controlled failure status overflow; retained originals: " + str(workspace)))
        elf = compiler._compiler_read_v1(workspace / "engine", 1048576)
        if len(elf) < 64 or elf[:7] != b"\x7fELF\x02\x01\x01" or int.from_bytes(elf[18:20], "little") != 62:
            raise AssertionError("controlled compiler did not produce a bounded amd64 ELF")
        compiler._compiler_preparation_clock_v1(kwargs["absolute_deadline_ns"])
        with executable.open("xb") as stream:
            if stream.write(elf) != len(elf):
                raise AssertionError("controlled ELF copy was short")
            compiler._compiler_preparation_clock_v1(kwargs["absolute_deadline_ns"])
            stream.flush()
            compiler._compiler_preparation_clock_v1(kwargs["absolute_deadline_ns"])
            os.fsync(stream.fileno())
        compiler._compiler_preparation_clock_v1(kwargs["absolute_deadline_ns"])
        executable.chmod(0o700)
        compiler._compiler_preparation_clock_v1(kwargs["absolute_deadline_ns"])
        return {"accepted": True, "normal_closed": True, "receipt_persisted": True,
                "controlled_test_only": True, "physical_qualification": False}

    try:
        with patch.object(compiler, "preflight_fixture_engine_v1", side_effect=preflight), \
                patch.object(compiler, "compile_fixture_engine_v1", side_effect=compile_external):
            yield authority
    except BaseException:
        # Keep failed originals and scratch, even when the enclosing test cleans its root.
        for workspace in workspaces:
            print("controlled compiler retained originals: " + str(workspace), file=sys.stderr)
        raise
    else:
        for workspace in workspaces:
            shutil.rmtree(workspace)
