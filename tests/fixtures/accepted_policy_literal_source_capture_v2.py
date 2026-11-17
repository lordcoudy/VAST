"""The two literal producers' fixed source slots, using the unchanged D16 owner.

External exact-source/runtime/configuration and quiescent-directory admission is
mandatory. Held/pre-post directory checks do not anchor absolute-path writes
against a concurrent rename. This module grants no execution or capacity authority.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import signal
import threading

from publication_operational_request_domain_v1 import strict_json_object_v1
from publication_physical_io_v1 import PhysicalRootCustodyV1
from tests.fixtures.accepted_policy_standalone_reader_fixture_v2 import (
    CHANNEL_LIMIT, RESULT_LIMIT, _bounded_json_v2, _capture_owned_reader_v2,
    _children_v2, _monotonic_ns, _sealed_deadline_v2, _stat_fields_v2, _write_result_v2,
)

_WORKTREE = Path("/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST")
_GIT_DIR = "/mnt/e/STUDY/VAST/.git/worktrees/VAST8"
_APPROVED = "299c9c0eefb83fe3031096b0e96527236678a4d2"
_GUARDIAN = "scripts/publication_guardian_accepted_policy_preprocessing_contract_v1.py"
_POSITIVE = ("head", "status", "guardian")
_NEGATIVE = ("before-head", "before-status", "before-proof", "after-proof", "after-head", "after-status")
_CONFIG = (("gc.auto", "0"), ("maintenance.auto", "false"),
    ("core.fsmonitor", "false"), ("core.untrackedCache", "false"),
    ("core.preloadIndex", "false"), ("core.hooksPath", "/dev/null"),
    ("index.threads", "1"), ("pack.threads", "1"),
    ("core.packedGitWindowSize", "1048576"), ("core.packedGitLimit", "67108864"),
    ("core.deltaBaseCacheLimit", "16777216"))

# Stock helpers remain unchanged. The AS limit is active before Python imports;
# the existing verifier deadline covers its file/hash loop. Its internal Git
# spawns retain stock timeouts, under the enclosing original D16 owner clock.
_RAW_SOURCE_PROOF_V2 = """
import json,os,resource,stat,sys,time
from pathlib import Path
soft,hard=resource.getrlimit(resource.RLIMIT_AS)
if not 0<soft<=hard<=1073741824:
    raise ValueError('source proof address-space limit is unavailable')
root=Path(sys.argv[1]); end=int(sys.argv[2])
def clock():
    if time.monotonic_ns()>=end:
        raise RuntimeError('source proof observation deadline expired')
clock()
index=Path(os.environ['GIT_DIR'])/'index'
info=index.lstat()
if not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=4194304:
    raise ValueError('source proof index bound refused')
sys.path.insert(0,str(root/'scripts'))
import run_ci_checks as ci
if ci.__file__!=str(root/'scripts/run_ci_checks.py'):
    raise ValueError('source proof verifier origin differs')
clock(); paths=ci.tracked_paths(root)
if type(paths) is not list or not 0<len(paths)<=16384 or len(set(paths))!=len(paths):
    raise ValueError('source proof path count refused')
total_paths=0; total_files=0; parents=set()
for relative in paths:
    clock()
    if type(relative) is not str or not relative or '\\\\' in relative:
        raise ValueError('source proof path type refused')
    raw=os.fsencode(relative); parts=relative.split('/')
    if len(raw)>512 or len(parts)>32 or any(part in ('','.','..') for part in parts):
        raise ValueError('source proof path bound refused')
    total_paths+=len(raw)+1
    if total_paths>2097152:
        raise ValueError('source proof path aggregate refused')
    path=root/relative; info=path.lstat()
    if (not stat.S_ISREG(info.st_mode) or path.resolve(strict=True)!=path
            or not 0<=info.st_size<=33554432):
        raise ValueError('source proof physical file bound refused')
    total_files+=info.st_size
    if total_files>1073741824:
        raise ValueError('source proof file aggregate refused')
    for count in range(1,len(parts)):
        parents.add('/'.join(parts[:count]))
        if len(parents)>32768:
            raise ValueError('source proof parent count refused')
clock(); ci.verify_committed_bytes(root,paths,absolute_deadline_ns=end); clock()
print(json.dumps({'raw_committed_bytes_verified':True,'tracked_path_count':len(paths),
    'verifier_path':ci.__file__},sort_keys=True))
"""


def _parent_limit_v2():
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    if (type(soft) is not int or type(hard) is not int
            or not 0 < soft <= hard <= 12 * 1024**3):
        raise ValueError("literal source capture requires finite parent soft/hard AS limits")


def _qualified_parent_v2(root):
    """Necessary local checks; external launch/runtime qualification is separate."""
    if not sys.platform.startswith("linux") or root != _WORKTREE or os.geteuid() != 1000:
        raise ValueError("literal source capture requires the selected ordinary Linux worktree")
    _parent_limit_v2()
    if (threading.active_count() != 1 or not hasattr(os, "pidfd_open")
            or not hasattr(signal, "pidfd_send_signal")):
        raise ValueError("literal source capture requires the unchanged D16 runtime prerequisites")
    for pid in _children_v2(os.getpid()):
        fields = _stat_fields_v2(pid)
        if fields is not None and fields[0] != b"Z":
            raise ValueError("literal source capture refuses a preexisting live child")


class LiteralSourceCaptureRefusedV2(ValueError):
    def __init__(self, evidence, *, primary=None, secondary=()):
        self.evidence, self.primary, self.secondary = evidence, primary, tuple(secondary)
        super().__init__("literal fixture source capture refused; original facts retained")


class LiteralSourceCaptureV2:
    def __init__(self, *, project_root, output_dir, capture_dir, deadline, expected_commit, negative=False):
        self.root = Path(project_root)
        _qualified_parent_v2(self.root)
        self.sealed = _sealed_deadline_v2(deadline)
        self.deadline = dict(deadline)
        if type(expected_commit) is not str or re.fullmatch(r"[0-9a-f]{40}", expected_commit) is None:
            raise ValueError("literal source capture requires an exact source commit")
        if type(negative) is not bool or not isinstance(capture_dir, (str, Path)):
            raise ValueError("literal source capture directory or recipe is missing")
        raw = os.fspath(capture_dir)
        self.directory, output = Path(raw), Path(output_dir)
        if (not raw or raw != os.path.normpath(raw) or not self.directory.is_absolute()
                or self.directory == self.root or not self.directory.is_relative_to(self.root)
                or self.directory == output or self.directory.is_relative_to(output)
                or output.is_relative_to(self.directory) or len(os.fsencode(raw)) > 512
                or self.directory.resolve(strict=True) != self.directory or not self.directory.is_dir()):
            raise ValueError("literal source capture directory must be canonical and separate")
        self.expected_commit = expected_commit
        self.slots = _NEGATIVE if negative else _POSITIVE
        self.used, self.records = [], []
        self.custody = PhysicalRootCustodyV1.open(self.directory, label="literal source capture")
        try:
            self._namespace()
            for slot in self.slots:
                if any(path.exists() or path.is_symlink() for path in self._outputs(slot).values()):
                    raise ValueError("literal source capture roster is occupied")
        except BaseException as primary:
            try:
                self.custody.close()
            except BaseException as secondary:
                raise LiteralSourceCaptureRefusedV2({"records": self.records},
                    primary=primary, secondary=(secondary,)) from primary
            raise

    def __enter__(self):
        return self

    def __exit__(self, kind, primary, traceback):
        secondary = []
        for operation in (self._namespace, self.custody.close):
            try:
                operation()
            except BaseException as error:
                if error is not primary and not any(error is old for old in secondary):
                    secondary.append(error)
        if secondary:
            if primary is None:
                primary = secondary.pop(0)
            raise LiteralSourceCaptureRefusedV2({"records": self.records},
                primary=primary, secondary=secondary) from primary
        return False

    def _outputs(self, slot):
        return {"stdout": self.directory / (slot + ".stdout.raw"),
                "stderr": self.directory / (slot + ".stderr.raw"),
                "result": self.directory / (slot + ".result.v2.json")}

    def _namespace(self):
        self.custody.verify()
        allowed = {path.name for slot in self.used for path in self._outputs(slot).values()}
        count = 0
        with os.scandir(self.directory) as entries:
            for entry in entries:
                count += 1
                if count > 3 * len(self.slots) or entry.name not in allowed:
                    raise ValueError("literal source capture namespace is occupied or changed")
        self.custody.verify()

    def _command(self, slot):
        environment = ["PATH=/usr/bin:/bin", "LANG=C", "LC_ALL=C", "GIT_DIR=" + _GIT_DIR,
            "GIT_WORK_TREE=" + str(self.root), "GIT_CONFIG_NOSYSTEM=1", "GIT_CONFIG_SYSTEM=/dev/null",
            "GIT_CONFIG_GLOBAL=/dev/null", "GIT_ATTR_NOSYSTEM=1", "GIT_OPTIONAL_LOCKS=0",
            "GIT_NO_REPLACE_OBJECTS=1", "GIT_NO_LAZY_FETCH=1", "GIT_TERMINAL_PROMPT=0",
            "GIT_CONFIG_COUNT=" + str(len(_CONFIG))]
        for index, (key, value) in enumerate(_CONFIG):
            environment.extend((f"GIT_CONFIG_KEY_{index}={key}", f"GIT_CONFIG_VALUE_{index}={value}"))
        prefix = ["/usr/bin/env", "-i", *environment, "/usr/bin/prlimit",
                  "--as=1073741824:1073741824", "--"]
        if "proof" in slot:
            return [*prefix, sys.executable, "-I", "-S", "-B", "-c", _RAW_SOURCE_PROOF_V2,
                    str(self.root), str(self.sealed["observe_end_ns"])]
        args = ("rev-parse", "HEAD") if "head" in slot else (
            ("show", _APPROVED + ":" + _GUARDIAN) if slot == "guardian"
            else ("status", "--porcelain", "--untracked-files=no"))
        return [*prefix, "/usr/bin/git", "-C", str(self.root), *args]

    def _persist(self, slot, command, facts, outputs, *, observed_return_ns=None, clock_failed=False):
        record = {"schema_version": 2, "slot": slot, "command": command, "cwd": str(self.root),
            "source_commit": self.expected_commit, "capture_returned": facts is not None,
            "capture": facts, "capture_return_observed_ns": observed_return_ns,
            "post_return_clock_failed": clock_failed,
            "returned_within_observation": None if observed_return_ns is None else
                observed_return_ns < self.sealed["observe_end_ns"],
            "stdout_path": str(outputs["stdout"]), "stderr_path": str(outputs["stderr"]),
            "campaign_authority": False}
        raw = _bounded_json_v2(record, RESULT_LIMIT - 1)
        complete = raw is not None
        if raw is None:
            raw = _bounded_json_v2({"schema_version": 2, "slot": slot, "incomplete": True,
                "capture_returned": facts is not None, "campaign_authority": False}, RESULT_LIMIT - 1)
        raw += b"\n"
        evidence = {**record, "result_path": str(outputs["result"]), "result_complete": complete,
            "result_persistence": None, "result_sha256": hashlib.sha256(raw).hexdigest(),
            "causes": ["source_post_return_clock"] if clock_failed else []}
        self.records.append(evidence)
        try:
            evidence["result_persistence"] = _write_result_v2(
                outputs["result"], raw, self.sealed["absolute_monotonic_ns"])
        except BaseException as primary:
            raise LiteralSourceCaptureRefusedV2(evidence, primary=primary) from primary
        return evidence, raw

    def capture(self, slot):
        if type(slot) is not str or len(self.used) >= len(self.slots) or slot != self.slots[len(self.used)]:
            raise ValueError("literal source slot is unknown, reused or out of order")
        if _monotonic_ns() >= self.sealed["observe_end_ns"]:
            raise ValueError("literal source observation deadline expired")
        _qualified_parent_v2(self.root)
        self._namespace()
        outputs = self._outputs(slot)
        if any(path.exists() or path.is_symlink() for path in outputs.values()):
            raise ValueError("literal source slot is occupied")
        self.used.append(slot)
        command = self._command(slot)
        try:
            facts, stdout, stderr = _capture_owned_reader_v2(
                command=command, cwd=self.root, outputs=outputs, deadline=self.deadline)
        except BaseException as primary:
            try:
                evidence, _ = self._persist(slot, command, None, outputs)
            except BaseException as secondary:
                raise LiteralSourceCaptureRefusedV2({"slot": slot, "capture": None,
                    "capture_returned": False, "records": self.records}, primary=primary,
                    secondary=(secondary,)) from primary
            raise LiteralSourceCaptureRefusedV2(evidence, primary=primary) from primary
        try:
            observed_return_ns = _monotonic_ns()
        except BaseException as primary:
            try:
                evidence, _ = self._persist(slot, command, facts, outputs, clock_failed=True)
            except LiteralSourceCaptureRefusedV2 as persistence_error:
                evidence = persistence_error.evidence
                secondary = persistence_error.primary if persistence_error.primary is not None else persistence_error
                evidence["causes"].append("source_result_persistence_raised")
                distinct = () if secondary is primary else (secondary,)
                raise LiteralSourceCaptureRefusedV2(evidence, primary=primary, secondary=distinct) from primary
            raise LiteralSourceCaptureRefusedV2(evidence, primary=primary) from primary
        late = observed_return_ns >= self.sealed["observe_end_ns"]
        evidence, raw = self._persist(slot, command, facts, outputs, observed_return_ns=observed_return_ns)
        persistence = evidence["result_persistence"]
        complete = (evidence["result_complete"] and not late and not facts["causes"]
            and facts["forced"] is False and facts["signal"] is None
            and type(facts["returncode"]) is int and facts["returncode"] == 0
            and facts["closure"]["closed"] is True
            and facts["closure"]["descendants_unknown"] is False
            and facts["closure"]["subreaper_restored"] is True)
        for channel, payload in (("stdout", stdout), ("stderr", stderr)):
            row = facts[channel]
            digest = hashlib.sha256(payload).hexdigest()
            complete = complete and (type(payload) is bytes and len(payload) <= CHANNEL_LIMIT
                and row is not None and row["eof"] is True and row["overflow"] is False
                and row["remainder_unknown"] is False and row["discarded_bytes"] == 0
                and row["observed_bytes"] == row["retained_bytes"] == len(payload)
                and row["retained_sha256"] == digest and row["file"]["sha256"] == digest
                and row["file"]["written_bytes"] == len(payload)
                and row["file"]["write_extent_unknown"] is False
                and row["file"]["fsync_completed"] is True and row["file"]["close_completed"] is True)
        complete = complete and (persistence["attempted"] is True
            and type(persistence["written_bytes"]) is int and persistence["written_bytes"] == len(raw)
            and persistence["write_extent_unknown"] is False and persistence["fsync_completed"] is True
            and persistence["close_completed"] is True and not persistence["causes"]
            and _monotonic_ns() < self.sealed["absolute_monotonic_ns"])
        if not complete:
            evidence["causes"].append("source_observation_deadline" if late else "source_capture_or_persistence_incomplete")
            raise LiteralSourceCaptureRefusedV2(evidence)
        try:
            for role, payload in (("stdout", stdout), ("stderr", stderr), ("result", raw)):
                descriptor, _ = self.custody.read_descriptor(outputs[role], label="literal source " + role,
                    maximum=RESULT_LIMIT if role == "result" else CHANNEL_LIMIT, capture=False)
                if descriptor["size_bytes"] != len(payload) or descriptor["sha256"] != hashlib.sha256(payload).hexdigest():
                    raise ValueError("literal source completed file differs from returned facts")
            self._namespace()
            if _monotonic_ns() >= self.sealed["absolute_monotonic_ns"]:
                raise ValueError("literal source final verification deadline expired")
            if stderr:
                raise ValueError("literal source command returned unexpected stderr")
            if "head" in slot and stdout != (self.expected_commit + "\n").encode("ascii"):
                raise ValueError("literal source HEAD differs")
            if "status" in slot and stdout:
                raise ValueError("literal tracked source is not clean")
            if slot == "guardian" and not stdout:
                raise ValueError("literal approved guardian source is empty")
            if "proof" in slot:
                if len(stdout) > 8192:
                    raise ValueError("literal source proof exceeds its parsing ceiling")
                proof = strict_json_object_v1(stdout, max_bytes=8192)
                if (set(proof) != {"raw_committed_bytes_verified", "tracked_path_count", "verifier_path"}
                        or proof["raw_committed_bytes_verified"] is not True
                        or type(proof["tracked_path_count"]) is not int or not 0 < proof["tracked_path_count"] <= 16384
                        or proof["verifier_path"] != str(self.root / "scripts/run_ci_checks.py")):
                    raise ValueError("literal stock source proof identity differs")
                returned = {"command": command, "original_exit_code": facts["returncode"],
                    "stdout": stdout.decode("utf-8"), "stderr": "",
                    "capture_result": {"path": str(outputs["result"]), "sha256": evidence["result_sha256"]},
                    "result_persistence": persistence}
                if _monotonic_ns() >= self.sealed["absolute_monotonic_ns"]:
                    raise ValueError("literal source proof return deadline expired")
                return returned
            if _monotonic_ns() >= self.sealed["absolute_monotonic_ns"]:
                raise ValueError("literal source return deadline expired")
            return stdout
        except BaseException as primary:
            evidence["causes"].append("source_completed_file_or_protocol_refused")
            raise LiteralSourceCaptureRefusedV2(evidence, primary=primary) from primary

    def git(self, root, *args, slot):
        expected = ("rev-parse", "HEAD") if slot in ("head", "before-head", "after-head") else (
            ("show", _APPROVED + ":" + _GUARDIAN) if slot == "guardian"
            else ("status", "--porcelain", "--untracked-files=no"))
        if Path(root) != self.root or args != expected or slot not in self.slots or "proof" in slot:
            raise ValueError("literal Git request differs from its fixed slot")
        return self.capture(slot)

    def proof(self, root, *, slot):
        if Path(root) != self.root or slot not in ("before-proof", "after-proof"):
            raise ValueError("literal proof request differs from its fixed slot")
        return self.capture(slot)
