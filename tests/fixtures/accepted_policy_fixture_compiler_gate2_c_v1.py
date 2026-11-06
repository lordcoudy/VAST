"""Fixed task-2.10 C1--C6 admission and independent comparison."""
from __future__ import annotations

import base64
import hashlib
from contextlib import contextmanager, nullcontext
import json
import os
from pathlib import Path, PureWindowsPath
import re
import select
import signal
import stat
import struct
import subprocess
import sys
import time

try:
  if __name__ == "__main__":
    _native_args = sys.argv[1:]
    _native_commit = _native_args[1] if len(_native_args) == 5 else ""
    if re.fullmatch("[0-9a-f]{40}", _native_commit) is None or _native_args[0] not in ("C1", "C2", "C3", "C4", "C5", "C6"):
      raise ValueError("fixed native arguments")
    _native_root = Path("/home/s-a-balashov/work/vast-fixture-compiler-gate2-" + _native_commit + "-01")
    if Path(__file__).resolve(strict=True) != _native_root / "tests/fixtures/accepted_policy_fixture_compiler_gate2_c_v1.py":
      raise ValueError("fixed native export")
    sys.path[:0] = [str(_native_root), str(_native_root / "scripts")]
  from tests.fixtures import accepted_policy_fixture_compiler_component_v1 as component
  from tests.fixtures import accepted_policy_fixture_compiler_v1 as compiler
except BaseException:
  if __name__ == "__main__":
    try:
      os.write(2, b'{"cause":"c_native_bootstrap","unknown":true}\n')
    except OSError:
      pass
    raise SystemExit(1)
  raise

STAGES = ("C1", "C2", "C3", "C4", "C5", "C6")
SEAL_BYTES = 536870912
C_LIMIT = 67108864
CONTROL_LIMIT = 4194304
RUNTIME_STOP = 16777216
RUN_NS = 150_000_000_000
COMPLETION_RESERVE_NS = 1_000_000_000
PACKET_LIMIT = 131072
RESUME_PACKET_LIMIT_V1 = 32768
RESUME_PRODUCER_COMMIT_V1 = "465ab7986939c67ae3594344ee3b6266cd2abd7a"
RESUME_OWNER_ROOT_V1 = Path("/home/s-a-balashov/work/vast-fixture-compiler-gate2-" + RESUME_PRODUCER_COMMIT_V1 + "-01")
RESUME_ROOT_V1 = RESUME_OWNER_ROOT_V1 / "r1"
RESUME_OPERATOR_V1 = "tests/fixtures/accepted_policy_fixture_compiler_gate2_resume_v1.py"
RESUME_INITIAL_CHARGE_V1 = 29323264
RECORD_LIMIT = 524288
CRASH_DIRECTORY = Path("/mnt/c/Users/s-a-balashov/AppData/Local/Temp/wsl-crashes")
REVIEW_REPO_ROOT_WINDOWS_V1 = PureWindowsPath(r"C:\Users\s-a-balashov\.codex\worktrees\fix-accepted-policy-preprocessing\VAST")
B_CIDS = (
  "4df593e12ca362e69f0594b2035197335f335d3ceae3c71894b31db9f197a09f",
  "9b5c396109909a8a091a0fc6bb6529f887233df77ab314435ce85ab05e22fbc5",
  "90f8ebb69bd83cbb02067a831cc2ace5efe78fc6b568a665bd93333d7b4b6e87",
)
MOUNTS_SHA256 = "3da03bbba33c8c86f2935cfcfcc07f16bb4020337d8d130deb5d8595851ff470"
EXPECTED = {
  "engine_id": "1e493309-3767-45fb-9078-05b838bdfd80", "server_version": "29.7.2",
  "kernel": "6.6.87.2-microsoft-standard-WSL2", "driver": "overlayfs", "cgroup_driver": "systemd",
  "security_options": ["name=seccomp,profile=builtin", "name=cgroupns"],
  "runtimes_sha256": "b480bc9619d585079ca9926e520ee190fc971f2e7c2c6c01b5256ac058c4a5d1",
  "provider_size": 10469582904,
  "rootfs_sha256": "1e0fe0c49e48962dc125b19e5b1936c564f1c6a3e00006d5e5cca7dc7ebfd981",
  "env_keys_sha256": "6785bc7c38e52df3c99c3856d0619875fc1a1f44aab077baa550da820b8f1db9",
  "platform_manifest": compiler.PROVIDER_PLATFORM_MANIFEST, "unpacked_bytes": 18930790400,
}
CODE_PATHS = (
  "tests/fixtures/accepted_policy_fixture_compiler_gate2_c_v1.py",
  "tests/fixtures/accepted_policy_fixture_compiler_component_v1.py",
  "tests/fixtures/accepted_policy_fixture_compiler_v1.py",
  "tests/fixtures/accepted_policy_fixture_compiler_publisher_v1.py",
  "tests/fixtures/accepted_policy_fixture_compiler_seccomp_v1.json",
  "scripts/publication_operational_request_domain_v1.py",
  "tests/fixtures/accepted_policy_fixture_compiler_recovery_v1.py",
  "tests/fixtures/accepted_policy_fixture_compiler_gate2_p0_v1.py",
  "tests/fixtures/accepted_policy_fixture_compiler_gate2_d_v1.py",
  "tests/fixtures/accepted_policy_fixture_compiler_gate2_d_child_v1.py",
)
PROOF_SOURCES = {
  "baseline": ("b1_result", "b1_report", "b2_index"),
  "toolchain": ("b1_report", "f2_supplement", "f2_index"),
  "abi": ("b1_report", "b2_report", "b2_result", "b2_index"),
  "limits": ("b1_report", "b1_result", "b2_report", "b2_index"),
  "closure": ("b1_result", "b2_result", "b3_result", "b2_index"),
}
B_ORIGINAL_SHA256 = {
  "b1_result": "9e722bd6b79d326c049da1083a7be14f8258e1a93ff04a18ed7c224756e118c5",
  "b1_report": "4f7dfcabe66e93326b454bb8a4ff0a38136b698da8de042086740b8486d10e90",
  "b2_result": "89fb2dd2ec3b1d0f4702ab6c0b15431147db4e64f38326b266665d3e351c2bd4",
  "b2_report": "ef203c57e1797bbf2556a494a2a0f22730f007638be5916b6bd1045831457535",
  "b3_result": "04fe470728acf9083b818a18a7620a45c52acb8a49f3ba12dcf13ecb045d1f18",
  "b2_manifest": "87c50e14f1a9ce3f5b0ff8ca2e4589e747ceb7ae5561671406e3da7a0c8f76d4",
}
EVIDENCE_NAMES = tuple(B_ORIGINAL_SHA256) + ("b2_index", "f2_supplement", "f2_index", "f2_accounting")
OPTIONAL_CODE_PATHS = (
  "tests/fixtures/accepted_policy_fixture_compiler_gate2_d_v1.py",
  "tests/fixtures/accepted_policy_fixture_compiler_gate2_d_child_v1.py",
  "tests/fixtures/accepted_policy_fixture_compiler_recovery_v1.py",
  "tests/fixtures/accepted_policy_fixture_compiler_gate2_p0_v1.py",
)


class Gate2Refusal(RuntimeError):
  def __init__(self, cause, facts=None):
    super().__init__(cause)
    self.cause, self.facts = cause, {} if facts is None else facts


def _require(condition, cause):
  if not condition:
    raise Gate2Refusal(cause)


def _sha(raw):
  return hashlib.sha256(raw).hexdigest()


def _sha_shape(value):
  return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None


def _resume_candidate_root_v1(commit, size, digest):
  root = RESUME_ROOT_V1
  if not os.path.lexists(root):
    return None
  _require(root.is_absolute() and root.resolve(strict=True) == root and root.is_dir()
    and root.parent == RESUME_OWNER_ROOT_V1 and size <= RESUME_PACKET_LIMIT_V1, "resume_native_root")
  raw = _bound_descriptor({"path": str(root / "gate2.packet.original.json"),
    "size_bytes": size, "sha256": digest}, root=root, cap=RESUME_PACKET_LIMIT_V1)
  packet = _json(raw, RESUME_PACKET_LIMIT_V1)
  context = packet.get("resume_context")
  _require(type(packet.get("schema_version")) is int and packet["schema_version"] == 1 and
    packet.get("artifact_kind") == "vast_fixture_compiler_gate2_packet_v1" and
    packet.get("code_commit") == commit and packet.get("project_root") == str(root) and
    type(context) is dict and type(context.get("schema_version")) is int and
    context["schema_version"] == 1 and context.get("producer_commit") == RESUME_PRODUCER_COMMIT_V1 and
    context.get("consumer_commit") == commit and context.get("project_root") == str(root) and
    context.get("owner_project_root") == str(RESUME_OWNER_ROOT_V1), "resume_native_binding")
  return root


def parse_native_invocation_v1(args, *, stage):
  _require(stage in STAGES + ("D",) and type(args) is list and len(args) == 4 and
    all(type(value) is str and len(value) <= 512 for value in args), "native_arguments")
  commit, size, digest, prior = args
  _require(re.fullmatch("[0-9a-f]{40}", commit) and _sha_shape(digest) and
    re.fullmatch("[1-9][0-9]{0,5}", size) and int(size) <= PACKET_LIMIT, "native_authority")
  candidate = _resume_candidate_root_v1(commit, int(size), digest)
  root = (str(candidate) if candidate is not None else
    "/home/s-a-balashov/work/vast-fixture-compiler-gate2-" + commit + "-01")
  count = 6 if stage == "D" else STAGES.index(stage)
  rows = [] if prior == "-" else prior.split(",")
  _require(len(rows) == count and (count != 0 or prior == "-"), "native_prior_count")
  authorities = {}
  for name, row in zip(STAGES, rows):
    match = re.fullmatch("([1-9][0-9]{0,3}):([0-9a-f]{64})", row)
    _require(match is not None and int(match[1]) <= 8192, "native_prior_descriptor")
    authorities[name] = {"path": root + "/outputs/" + name + "/outer.invocation.original.json",
      "size_bytes": int(match[1]), "sha256": match[2]}
  return {"project_root": root, "packet_descriptor": {"path": root + "/gate2.packet.original.json",
    "size_bytes": int(size), "sha256": digest}, "expected_packet_sha256": digest,
    "expected_code_commit": commit, "completion_authorities": authorities}


def native_failure_bytes_v1(error):
  cause = getattr(error, "cause", type(error).__name__)
  def label(value):
    return re.sub("[^a-zA-Z0-9_.:/-]", "?", value[:32]) if type(value) is str else "unknown"
  facts = getattr(error, "facts", None)
  value = {"cause": label(cause), "causes": [], "physical_acceptance": False,
    "external_status_eof_required": True, "facts_unknown": True, "facts_remainder_unknown": True}
  if type(cause) is not str or label(cause) != cause:
    value["cause_remainder_unknown"] = True
  pending, seen, observations = [("", facts, 0)], set(), []
  for _ in range(24):
    if not pending:
      break
    path, row, depth = pending.pop(0)
    if type(row) is not dict or id(row) in seen:
      continue
    seen.add(id(row))
    causes = row.get("causes", row.get("failure_causes", []))
    candidates = ([row["cause"]] if type(row.get("cause")) is str else [])
    if type(causes) is list:
      candidates += causes[:4]
    for item in candidates:
      item = label(item)
      if item not in value["causes"] and len(value["causes"]) < 4:
        value["causes"].append(item)
    for key in ("write_extent_unknown", "unknown_closure", "closed", "stdout_eof", "stderr_eof", "returncode", "written_bytes"):
      item = row.get(key)
      if len(observations) < 2 and (type(item) is bool or type(item) is int and -(2**63) <= item < 2**63):
        observations.append([path, key, item])
    if depth < 3:
      for key in ("failure_facts", "owner_facts", "refusal_write_failure", "write_facts", "child", "files", "stdout", "stderr"):
        if type(row.get(key)) is dict:
          pending.append(((path + "." + key).lstrip("."), row[key], depth + 1))
  if observations:
    value["observations"] = observations
  try:
    _require(compiler._json_bound(facts) <= CONTROL_LIMIT, "native_failure_facts_bound")
    raw = component.canonical_json_v1(facts)
    value.update(facts_unknown=False, facts_bytes=len(raw), facts_sha256=_sha(raw),
      facts_prefix_base64=base64.b64encode(raw[:16]).decode("ascii"))
  except (Gate2Refusal, ValueError, TypeError, RecursionError, OverflowError):
    pass
  raw = component.canonical_json_v1(value) + b"\n"
  if len(raw) > 768:
    value.pop("facts_prefix_base64", None)
    raw = component.canonical_json_v1(value) + b"\n"
  while len(raw) > 768 and value.get("observations"):
    value["observations"].pop()
    raw = component.canonical_json_v1(value) + b"\n"
  return raw


def emit_native_bytes_v1(raw, deadline):
  facts = {"written_bytes": 0, "write_extent_unknown": False, "flush_completed": False}
  _require(type(raw) is bytes and 0 < len(raw) <= 2048 and raw.endswith(b"\n") and
    raw.isascii() and type(deadline) is int, "native_stdout_shape")
  try:
    _require(time.monotonic_ns() < deadline, "native_stdout_deadline")
    try:
      written = os.write(sys.stdout.fileno(), raw)
    except (OSError, ValueError):
      facts["write_extent_unknown"] = True
      raise
    if type(written) is not int or not 0 <= written <= len(raw):
      facts["write_extent_unknown"] = True
      raise Gate2Refusal("native_stdout_contract")
    facts["written_bytes"] = written
    _require(written == len(raw), "native_stdout_short_write")
    _require(time.monotonic_ns() < deadline, "native_stdout_deadline")
    sys.stdout.flush()
    facts["flush_completed"] = True
    _require(time.monotonic_ns() < deadline, "native_stdout_deadline")
  except (Gate2Refusal, OSError, ValueError) as error:
    raise Gate2Refusal(getattr(error, "cause", "native_stdout_" + type(error).__name__), facts) from error


def native_main_v1(argv=None):
  try:
    args = sys.argv[1:] if argv is None else argv
    _require(type(args) is list and len(args) == 5 and args[0] in STAGES + ("D",), "native_stage")
    if args[0] == "D":
      from tests.fixtures import accepted_policy_fixture_compiler_gate2_d_v1 as stage_d
      return stage_d.native_main_v1(args[1:])
    stage, kwargs = args[0], parse_native_invocation_v1(args[1:], stage=args[0])
    returned = run_c_v1(stage, **kwargs)
    completed = complete_c_invocation_v1(stage, project_root=kwargs["project_root"], returned_result=returned,
      expected_packet_sha256=kwargs["expected_packet_sha256"], expected_code_commit=kwargs["expected_code_commit"])
    emit_native_bytes_v1(component.canonical_json_v1(completed) + b"\n", completed["completion_deadline_ns"])
    return 0
  except BaseException as error:
    try:
      os.write(2, native_failure_bytes_v1(error))
    except OSError:
      pass
    return 1


def _json(raw, cap=RECORD_LIMIT, *, canonical=True):
  _require(type(raw) is bytes and 0 < len(raw) <= cap, "json_bound")
  def unique(pairs):
    value = {}
    for key, item in pairs:
      if key in value:
        raise ValueError("duplicate key")
      value[key] = item
    return value
  try:
    value = json.loads(raw.decode("ascii"), object_pairs_hook=unique,
      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite")))
    _require(compiler._json_bound(value) <= cap * 2, "json_shape")
    _require(not canonical or component.canonical_json_v1(value) == raw, "json_canonical")
    return value
  except (ValueError, UnicodeError, RecursionError, TypeError) as error:
    raise Gate2Refusal("json_invalid") from error


def _read(path, cap):
  try:
    raw, _ = component._retention_read_v1(path, cap)
    return raw
  except component.ComponentRecipeError as error:
    raise Gate2Refusal("physical_file",getattr(error,"facts",{})) from error


def _descriptor(path, raw):
  return {"path": str(path), "size_bytes": len(raw), "sha256": _sha(raw)}


def _rpc_json_facts_v1(value):
  if value is None:
    return None
  _require(type(value) is dict and type(value.get("rpc")) is list and len(value["rpc"]) <= 23, "rpc_fact_shape")
  result, rows = dict(value), []
  for original in value["rpc"]:
    _require(type(original) is dict and len(original) <= 64, "rpc_fact_row")
    row = dict(original)
    for name in ("epoch_before", "epoch_after"):
      epoch = row.get(name)
      if epoch is None:
        continue
      _require(type(epoch) in (tuple, list) and len(epoch) == 3 and all(
        type(item) in (tuple, list) and len(item) == 6 and all(
        type(number) is int and number >= 0 or number is None for number in item) for item in epoch), "rpc_epoch_shape")
      row[name] = [list(item) for item in epoch]
    rows.append(row)
  result["rpc"] = rows
  return result


def _resume_info_identity_v1(info):
  _require(type(info) is dict, "resume_info_shape")
  value = {"engine_id": info.get("ID"), "server_version": info.get("ServerVersion"),
    "kernel": info.get("KernelVersion"), "driver": info.get("Driver"),
    "cgroup_driver": info.get("CgroupDriver"), "security_options": info.get("SecurityOptions"),
    "runtimes_sha256": _sha(component.canonical_json_v1(info.get("Runtimes"))),
    "docker_root_dir": info.get("DockerRootDir"), "cgroup_version": info.get("CgroupVersion"),
    "containers": info.get("Containers"), "containers_running": info.get("ContainersRunning"),
    "containers_paused": info.get("ContainersPaused"), "containers_stopped": info.get("ContainersStopped")}
  expected = {name: EXPECTED[name] for name in ("engine_id", "server_version", "kernel", "driver",
    "cgroup_driver", "security_options", "runtimes_sha256")}
  expected.update(docker_root_dir="/var/lib/docker", cgroup_version="2", containers=3,
    containers_running=0, containers_paused=0, containers_stopped=3)
  _require(component.canonical_json_v1(value) == component.canonical_json_v1(expected), "resume_info_identity")
  return value


def resume_info_v1(*, info, rpc_facts, request_raw, reply_raw):
  _require(type(request_raw) is bytes and type(reply_raw) is bytes and
    0 < len(request_raw) + len(reply_raw) <= 16384, "resume_info_wire_bound")
  _require(request_raw == b"GET /v1.55/info HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\nContent-Length: 0\r\n\r\n",
    "resume_info_request")
  _require(compiler._json_bound(info)<=32768,"resume_info_shape")
  actual = _http_json_v1(reply_raw)
  _require(component.canonical_json_v1(actual) == component.canonical_json_v1(info), "resume_info_raw_binding")
  identity = _resume_info_identity_v1(actual)
  facts = _rpc_json_facts_v1(rpc_facts)
  _require(type(facts.get("attempts")) is int and facts["attempts"] == 1 and len(facts["rpc"]) == 1 and
    type(facts.get("metadata_bytes")) is int and facts["metadata_bytes"] ==
    2 * (len(request_raw) + len(reply_raw)), "resume_info_transport")
  row = facts["rpc"][0]
  _require(type(row.get("number")) is int and row["number"]==1,"resume_info_number")
  yes = ("complete", "request_persisted", "reply_persisted", "request_close_completed",
    "reply_close_completed", "request_send_complete", "reply_eof", "socket_closed")
  no = ("request_write_extent_unknown", "reply_write_extent_unknown", "request_persistence_failed",
    "reply_persistence_failed", "upgraded")
  _require(all(row.get(key) is True for key in yes) and all(row.get(key) is False for key in no) and
    row.get("causes") == [] and facts.get("controlled_socket") is False and
    facts.get("controlled_clock") is False and type(row.get("status")) is int and row["status"] == 200,
    "resume_info_closure")
  for role, raw, keys in (("request", request_raw, ("bytes", "written_bytes", "persisted_bytes")),
    ("reply", reply_raw, ("observed_bytes", "retained_bytes", "written_bytes", "persisted_bytes"))):
    _require(all(type(row.get(role + "_" + key)) is int and row[role + "_" + key] == len(raw)
      for key in keys), "resume_info_extent")
  peer = row.get("peer")
  _require(type(peer) is dict and set(peer) == {"pid", "uid", "gid"} and
    all(type(peer[key]) is int for key in peer) and peer["pid"] > 0 and
    peer["uid"] == 0 and peer["gid"] >= 0 and row.get("epoch_before") is not None and
    row["epoch_before"] == row.get("epoch_after"), "resume_info_peer_epoch")
  summary = {key: row[key] for key in yes + no + ("causes", "peer")}
  summary.update(controlled_socket=False, controlled_clock=False, attempts=1, metadata_bytes=facts["metadata_bytes"])
  return {"request": {"size_bytes": len(request_raw), "sha256": _sha(request_raw)},
    "reply": {"size_bytes": len(reply_raw), "sha256": _sha(reply_raw)}, "identity": identity,
    "status": 200, "epoch_sha256": _sha(component.canonical_json_v1(row["epoch_before"])),
    "rpc_sha256": _sha(component.canonical_json_v1(row)), "rpc_summary": summary}


def _bound_descriptor(value, *, root=None, cap=RECORD_LIMIT):
  _require(type(value) is dict and set(value) == {"path", "size_bytes", "sha256"}
    and type(value["size_bytes"]) is int and 0 <= value["size_bytes"] <= cap
    and _sha_shape(value["sha256"]), "descriptor")
  path = Path(value["path"])
  if root is not None:
    _require(path.is_absolute() and path.is_relative_to(root), "descriptor_root")
  raw = _read(path, cap)
  _require(len(raw) == value["size_bytes"] and _sha(raw) == value["sha256"], "descriptor_drift")
  return raw


def write_record_v1(path, value, *, cap=RECORD_LIMIT, absolute_deadline_ns=None, return_facts=False):
  """Bound before encoding, exclusively persist and close one new original."""
  path = Path(path)
  _require(type(return_facts) is bool, "record_return_facts")
  _require(path.is_absolute() and path.parent.resolve(strict=True) == path.parent, "record_parent")
  facts = {"path": str(path), "open_completed": False, "written_bytes": 0, "write_extent_unknown": False,
    "flush_completed": False, "fsync_completed": False, "close_completed": False,
    "directory_persisted": False, "complete": False, "deadline_failed": False, "failure_causes": []}
  file, raw, failure = None, None, None
  phase = "bound"
  def check():
    if absolute_deadline_ns is not None:
      if type(absolute_deadline_ns) is not int or time.monotonic_ns() >= absolute_deadline_ns:
        facts["deadline_failed"] = True
        raise Gate2Refusal("record_deadline")
  try:
    check()
    _require(compiler._json_bound(value) <= cap, "record_bound")
    check()
    raw = component.canonical_json_v1(value)
    _require(len(raw) <= cap, "record_bound")
    check()
    phase = "open"
    file = path.open("xb", buffering=0)
    facts["open_completed"] = True
    check()
    phase = "write"
    try:
      written = file.write(raw)
    except (OSError, ValueError):
      facts["write_extent_unknown"] = True
      raise
    if type(written) is not int or not 0 <= written <= len(raw):
      facts["write_extent_unknown"] = True
      raise Gate2Refusal("record_write_contract")
    facts["written_bytes"] = written
    check()
    _require(written == len(raw), "record_short_write")
    phase = "flush"
    file.flush()
    facts["flush_completed"] = True
    check()
    phase = "fsync"
    os.fsync(file.fileno())
    facts["fsync_completed"] = True
    check()
  except FileExistsError:
    raise
  except (Gate2Refusal, OSError, ValueError, TypeError, RecursionError) as error:
    failure = error
    facts["failure_causes"].append("record_" + phase + "_" + type(error).__name__)
  finally:
    if file is not None:
      try:
        phase = "close"
        file.close()
        facts["close_completed"] = True
        check()
      except (Gate2Refusal, OSError, ValueError) as error:
        facts["failure_causes"].append("record_close_" + type(error).__name__)
        failure = failure or error
  if failure is None:
    try:
      check()
      phase = "directory_sync"
      compiler._compiler_directory_sync_v1(path.parent)
      facts["directory_persisted"] = True
      check()
    except (Gate2Refusal, OSError, ValueError) as error:
      facts["failure_causes"].append("record_" + phase + "_" + type(error).__name__)
      failure = error
  if failure is not None:
    cause = failure.cause if isinstance(failure, Gate2Refusal) else "record_" + type(failure).__name__
    raise Gate2Refusal(cause, facts) from failure
  facts["complete"] = True
  descriptor = _descriptor(path, raw)
  return {"descriptor": descriptor, "write_facts": facts} if return_facts else descriptor


def reserve_v1(*, charged, liability, c_free_bytes):
  _require(all(type(value) is int and value >= 0 for value in (charged, liability, c_free_bytes)), "ledger_unknown")
  _require(charged + liability <= SEAL_BYTES, "ledger_reserve")
  _require(c_free_bytes >= component.C_BYTES + component.ADDITIONAL_DISK_UPPER_BYTES, "capacity_floor")
  return charged + liability


def interval_charge_v1(before, after, *, retained_bytes, size_rw=0):
  names = ("c_free_bytes", "ext4_used_bytes")
  _require(type(before) is dict and type(after) is dict and all(
    type(row.get(name)) is int and row[name] >= 0 for row in (before, after) for name in names), "measurement_unknown")
  _require(type(retained_bytes) is int and retained_bytes >= 0 and type(size_rw) is int and size_rw >= 0, "measurement_unknown")
  return max(0, before["c_free_bytes"] - after["c_free_bytes"],
    after["ext4_used_bytes"] - before["ext4_used_bytes"], retained_bytes + size_rw)


def _b2_index_value(b_root):
  b_root = Path(b_root)
  _require(b_root.is_absolute() and b_root.resolve(strict=True) == b_root, "b_root")
  manifest_path = b_root / "runs/B2.originals.sha256"
  raw = _read(manifest_path, 16384)
  _require(_sha(raw) == B_ORIGINAL_SHA256["b2_manifest"], "b2_manifest_authentication")
  files = {}
  for line in raw.decode("ascii").splitlines():
    matched = re.fullmatch(r"([0-9a-f]{64})  ((?:outputs/B2/|runs/B2\.)[A-Za-z0-9_.-]+)", line)
    _require(matched is not None and matched[2] not in files, "b2_manifest_entry")
    expected, relative = matched.groups()
    value = _read(b_root / relative, 1048576)
    if relative == "runs/B2.originals.sha256":
      expected = B_ORIGINAL_SHA256["b2_manifest"]
    _require(_sha(value) == expected, "b2_original_drift")
    files[relative] = _descriptor(b_root / relative, value)
  _require("runs/B2.originals.sha256" in files, "b2_manifest_missing")
  return {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_b2_corrected_index_v1",
    "b_root": str(b_root), "original_manifest_sha256": _sha(raw), "files": files}


def build_b2_index_v1(*, b_root, output_path):
  return write_record_v1(Path(output_path), _b2_index_value(b_root), cap=65536)


def _relative_original(root, descriptor, cap):
  _require(type(descriptor) is dict and set(descriptor) == {"relative_path", "size_bytes", "sha256"}, "relative_descriptor")
  relative = descriptor["relative_path"]
  _require(type(relative) is str and not Path(relative).is_absolute() and
    "\\" not in relative and all(part not in ("", ".", "..") for part in relative.split("/")), "relative_path")
  return _bound_descriptor({"path": str(root / relative), "size_bytes": descriptor["size_bytes"],
    "sha256": descriptor["sha256"]}, root=root, cap=cap)


def _authenticate_evidence(evidence, review, plan_sha):
  _require(type(evidence) is dict and set(evidence) == set(EVIDENCE_NAMES), "proof_sources")
  actual = {name: _bound_descriptor(desc, cap=component.F2_FOOTER_LIMIT_V1 if name == "f2_accounting" else 1048576)
    for name, desc in evidence.items()}
  for name, expected in B_ORIGINAL_SHA256.items():
    _require(_sha(actual[name]) == expected, "b_original_authentication_" + name)
  for name, cid in zip(("b1_result", "b2_result", "b3_result"), B_CIDS):
    original = _json(actual[name], 1048576)
    _require(original.get("cid") == cid and (original.get("closure") or {}).get("closed") is True, "b_identity_closure")
  corrected = _json(actual["b2_index"], 65536)
  _require(corrected == _b2_index_value(corrected.get("b_root")), "b2_index_drift")
  supplement = _json(actual["f2_supplement"], 262144)
  _require(supplement.get("artifact_kind") == "vast_fixture_compiler_toolchain_recovery_v1" and
    supplement.get("complete") is True and supplement.get("causes") == [] and
    supplement.get("controlled") is False and supplement.get("cid") == B_CIDS[0] and
    supplement.get("provider_id") == compiler.PROVIDER_ID, "f2_complete_identity")
  f2_review = supplement.get("review") or {}
  _require(f2_review.get("commit") == review["commit"] and
    f2_review.get("physical_plan_sha256") == plan_sha, "f2_review_binding")
  f2_root = Path(evidence["f2_supplement"]["path"]).parent
  index_raw = _relative_original(f2_root, supplement["originals_index"], 262144)
  _require(index_raw == actual["f2_index"] and Path(evidence["f2_index"]["path"]) == f2_root / "f2.originals.v1.json", "f2_index_binding")
  from tests.fixtures import accepted_policy_fixture_compiler_recovery_v1 as recovery
  _require(hasattr(recovery, "validate_supplement_v1"), "f2_verifier_missing")
  recovery.validate_supplement_v1(output_dir=f2_root, supplement=supplement)
  _require(Path(evidence["f2_accounting"]["path"]) == f2_root / "f2.final-accounting.v1.json" and
    actual["f2_accounting"] == _read(f2_root / "f2.final-accounting.v1.json", component.F2_FOOTER_LIMIT_V1), "f2_accounting_binding")
  b1 = _json(actual["b1_report"], 1048576)
  environment = ((b1.get("report") or {}).get("environment") or {}).get("environment")
  _require(type(environment) is dict and _sha(component.canonical_json_v1(sorted(environment))) == EXPECTED["env_keys_sha256"], "b_environment")
  return {"environment_keys": sorted(environment), "accounting": _json(actual["f2_accounting"], component.F2_FOOTER_LIMIT_V1)["accounting"]}


def _proof_envelopes(evidence):
  return {kind: {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_component_proof_v1",
    "kind": kind, "provider_id": compiler.PROVIDER_ID, "b_cids": list(B_CIDS),
    "sources": {name: evidence[name] for name in names}}
    for kind, names in PROOF_SOURCES.items()}


def _verify_code(root, code):
  _require(type(code) is dict and set(CODE_PATHS) <= set(code) <= set(CODE_PATHS + OPTIONAL_CODE_PATHS), "packet_code_set")
  total = 0
  for relative, desc in code.items():
    _require(type(desc) is dict and set(desc) == {"size_bytes", "sha256", "git_blob"}, "code_descriptor")
    raw = _bound_descriptor({"path": str(root / relative), "size_bytes": desc["size_bytes"],
      "sha256": desc["sha256"]}, root=root, cap=262144)
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
    _require(type(desc["git_blob"]) is str and desc["git_blob"] == blob, "reviewed_git_blob_drift")
    total += len(raw)
  _require(total <= 640 * 1024, "code_allocation")


def _validate_p0(descriptor, root, commit, boot_id):
  from tests.fixtures import accepted_policy_fixture_compiler_gate2_p0_v1 as p0
  _bound_descriptor(descriptor, root=root, cap=65536)
  p0.validate_p0_originals_v1(descriptor, project_root=root, expected_code_commit=commit,
    expected_engine_id=EXPECTED["engine_id"], expected_boot_id=boot_id)


def _authenticate_prior_retention_v1(root, review, code, boot_id, authority_descriptor, prior):
  _require(compiler._json_bound(prior) <= 4096, "prior_retention_bound")
  expected = Path(str(root) + ".operator-originals") / "operator.authority.original.json"
  _require(type(authority_descriptor) is dict and authority_descriptor.get("path") == str(expected),
    "operator_authority_path")
  raw = _bound_descriptor(authority_descriptor, cap=8192)
  _require(_sha(raw) == review["evidence_sha256"], "operator_authority_binding")
  authority = _json(raw, 8192)
  names = {"schema_version", "code_commit", "approval_reference", "operator_sha256",
    "helper_code", "context_sha256", "context", "external_approval_required"}
  _require(type(authority) is dict and set(authority) == names and
    type(authority["schema_version"]) is int and authority["schema_version"] == 1 and
    authority["code_commit"] == review["commit"] and
    authority["approval_reference"] == review["approval_reference"] and
    authority["external_approval_required"] is True, "operator_authority_shape")
  context, helpers = authority["context"], authority["helper_code"]
  helper_paths = ("tests/fixtures/accepted_policy_fixture_compiler_gate2_setup_v1.py",
    "tests/fixtures/accepted_policy_fixture_compiler_gate2_capture_v1.py")
  _require(type(context) is dict and authority["context_sha256"] == _sha(component.canonical_json_v1(context))
    and context.get("code_commit") == review["commit"] and context.get("boot_id") == boot_id
    and component.canonical_json_v1(context.get("retention")) == component.canonical_json_v1(prior)
    and component.canonical_json_v1(context.get("helper_code")) == component.canonical_json_v1(helpers) and
    type(helpers) is dict and set(helpers) == set(helper_paths), "operator_context_binding")
  for relative in helper_paths:
    desc = helpers[relative]
    _require(type(desc) is dict and set(desc) == {"path", "size_bytes", "sha256", "git_blob"} and
      desc["path"] == str(REVIEW_REPO_ROOT_WINDOWS_V1 / relative) and
      type(desc["size_bytes"]) is int and 0 < desc["size_bytes"] <= 65536 and
      _sha_shape(desc["sha256"]) and type(desc["git_blob"]) is str and
      re.fullmatch("[0-9a-f]{40}", desc["git_blob"]), "operator_helper_descriptor")
    source = _bound_descriptor({"path": str(component.REVIEW_REPO_ROOT_LINUX_V1 / relative),
      "size_bytes": desc["size_bytes"], "sha256": desc["sha256"]}, cap=65536)
    _require(hashlib.sha1(b"blob " + str(len(source)).encode("ascii") + b"\0" + source).hexdigest()
      == desc["git_blob"], "operator_helper_binding")
  _require(authority["operator_sha256"] == helpers[helper_paths[0]]["sha256"] and
    context.get("capture_source_sha256") == helpers[helper_paths[1]]["sha256"],
    "operator_source_binding")
  _require(type(prior) is dict and set(prior) == {"git_observation", "native"} and
    type(prior["git_observation"]) is dict and
    component.canonical_json_v1(prior["git_observation"].get("component")) ==
    component.canonical_json_v1(code[CODE_PATHS[1]]), "prior_retention_shape")
  observation = prior["git_observation"]
  try:
    component.validate_prior_retention_receipt_v1(prior["native"],
      source_rows_sha256=observation["old_git_sha256"])
    fresh = component.verify_prior_retention_v1(component.REVIEW_REPO_ROOT_LINUX_V1,
      git_observation=observation)
    _require(all(fresh[name] == prior["native"][name] for name in
      ("index_sha256", "source_rows_sha256", "node_count")), "prior_retention_identity")
  except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError) as error:
    raise Gate2Refusal("prior_retention_unavailable") from error
  return fresh


def _resume_desc_v1(value, cap):
  _require(type(value) is dict and set(value) == {"size_bytes", "sha256", "git_blob"} and
    type(value["size_bytes"]) is int and 0 < value["size_bytes"] <= cap and _sha_shape(value["sha256"]) and
    type(value["git_blob"]) is str and re.fullmatch("[0-9a-f]{40}", value["git_blob"]), "resume_descriptor")


def _owner_project_root_v1(root, packet):
  if packet.get("resume_context") is None:
    return root
  context = packet["resume_context"]
  _require(root == RESUME_ROOT_V1 and context.get("project_root") == str(root) and
    context.get("owner_project_root") == str(RESUME_OWNER_ROOT_V1), "resume_owner_root")
  return RESUME_OWNER_ROOT_V1


def _resume_namespace_v1(root, stage=None):
  _require(stage is None or stage in STAGES + ("D",), "resume_namespace_stage")
  stages = () if stage is None else STAGES if stage == "D" else STAGES[:STAGES.index(stage) + 1]
  directories = {"p0", "outputs"}
  files = {"gate2.packet.original.json"} | {"p0/" + name for name in (
    "p0-control.v1.json", "p0-completion.v1.json", "p0-id.stdout.original", "p0-id.stderr.original",
    "p0-snapshot-info.stdout.original", "p0-snapshot-info.stderr.original",
    "p0-snapshot-ls.stdout.original", "p0-snapshot-ls.stderr.original")}
  for stage_name in stages:
    base = "outputs/" + stage_name + "/"
    directories.update({base[:-1], base + "controls", base + "engine.compiler-originals",
      base + "controls/identity", base + "controls/final-inspect"})
    files.update(base + name for name in ("engine.c", "component.seed.original.json", "component.admission.original.json",
      "outer.owner.original.json", "observations.original.json", "evaluation.original.json", "run.result.original.json",
      "run.accounting.original.json", "outer.invocation.original.json", "run.refusal.original.json"))
    files.update(base + "engine.compiler-originals/" + name for name in ("compiler.stdout.original",
      "compiler.stderr.original", "engine.unaccepted", "export.header.original", "export.prefix.original",
      "attach.headers.original", "client.stderr.original", "owner.result.original.json"))
    files.add(base + "controls/identity.original.json")
    for parent, count in (("engine.compiler-originals", 23), ("controls/identity", 4), ("controls/final-inspect", 1)):
      files.update(base + parent + "/RPC%02d.%s.original" % (n, role)
        for n in range(1, count + 1) for role in ("request", "reply"))
    for phase in ("before", "after"):
      prefix = base + "controls/" + phase
      directories.add(prefix)
      files.add(prefix + "/crashes.original.json")
      for kind in (("dmesg", "journal", "gpu") if phase == "before" else ("dmesg", "journal")):
        directories.add(prefix + "/" + kind)
        files.update(prefix + "/" + kind + "/" + kind + suffix for suffix in
          (".stdout.original", ".stderr.original", ".capture.original.json"))
  if stage == "D":
    directories.update({"outputs/D", "outputs/D/controls"})
    files.update({"outputs/D/engine", "outputs/D/" + component.D_STATE_FILE})
    files.update("outputs/D/controls/" + name for name in ("RPC01.request.original", "RPC01.reply.original",
      "d.stdout.original", "d.stderr.original", "d.preexec.original", "d.result.original.json"))
    for phase in ("before", "after"):
      files.add("outputs/D/controls/" + phase + ".crashes.original.json")
      files.update("outputs/D/controls/" + phase + "." + kind + "." + channel + ".original"
        for kind in ("dmesg", "journal", "gpu") for channel in ("stdout", "stderr"))
  pending, seen, count = [root], set(), 0
  device = root.stat().st_dev
  while pending:
    directory = pending.pop()
    with os.scandir(directory) as entries:
      for entry in entries:
        count += 1
        _require(count <= 1024, "resume_namespace_bound")
        path = Path(entry.path)
        info = path.lstat()
        relative = str(path.relative_to(root))
        _require(info.st_dev == device and (info.st_dev, info.st_ino) not in seen,
          "resume_namespace_backing_alias")
        seen.add((info.st_dev, info.st_ino))
        if stat.S_ISDIR(info.st_mode):
          _require(relative in directories and path.resolve(strict=True) == path, "resume_namespace_directory")
          pending.append(path)
        else:
          _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and relative in files,
            "resume_namespace_file")


def _resume_info_binding_v1(context):
  value, aux = context["pre_info"], Path(str(RESUME_ROOT_V1) + ".operator-originals")
  _require(type(value) is dict and set(value) == {"request", "reply", "identity", "status", "epoch_sha256",
    "rpc_sha256", "rpc_summary"} and type(value["status"]) is int and value["status"] == 200 and
    _sha_shape(value["epoch_sha256"]) and _sha_shape(value["rpc_sha256"]), "resume_pre_info")
  raws = {}
  for role in ("request", "reply"):
    desc = value[role]
    _require(type(desc) is dict and set(desc) == {"size_bytes", "sha256"}, "resume_info_descriptor")
    raws[role] = _bound_descriptor(dict(desc, path=str(aux / ("RPC01." + role + ".original"))), cap=16384)
  _require(0 < len(raws["request"]) + len(raws["reply"]) <= 16384 and raws["request"] ==
    b"GET /v1.55/info HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\nContent-Length: 0\r\n\r\n",
    "resume_info_wire_bound")
  identity = _resume_info_identity_v1(_http_json_v1(raws["reply"]))
  _require(component.canonical_json_v1(identity) == component.canonical_json_v1(value["identity"]), "resume_info_projection")
  yes = ("complete", "request_persisted", "reply_persisted", "request_close_completed",
    "reply_close_completed", "request_send_complete", "reply_eof", "socket_closed")
  no = ("request_write_extent_unknown", "reply_write_extent_unknown", "request_persistence_failed",
    "reply_persistence_failed", "upgraded", "controlled_socket", "controlled_clock")
  row = value["rpc_summary"]
  _require(type(row) is dict and set(row) == set(yes + no + ("causes", "peer", "attempts", "metadata_bytes")) and
    all(row[key] is True for key in yes) and all(row[key] is False for key in no) and row["causes"] == [] and
    type(row["attempts"]) is int and row["attempts"] == 1 and type(row["metadata_bytes"]) is int and
    row["metadata_bytes"] == 2 * sum(map(len, raws.values())), "resume_info_summary")
  peer = row["peer"]
  _require(type(peer) is dict and set(peer) == {"pid", "uid", "gid"} and all(type(n) is int for n in peer.values())
    and peer["pid"] > 0 and peer["uid"] == 0 and peer["gid"] >= 0, "resume_info_peer")


def _resume_aux_v1():
  caps = {"operator.authority.original.json": 8192, "operator.command.original.json": 4096,
    "p0.return.original.json": 4096, "resume.events.original.json": 8192,
    "RPC01.request.original": 16384, "RPC01.reply.original": 16384}
  aux = Path(str(RESUME_ROOT_V1) + ".operator-originals")
  with os.scandir(aux) as rows:
    for count, row in enumerate(rows, 1):
      _require(count <= 6 and row.name in caps, "resume_aux_inventory")
      info = row.stat(follow_symlinks=False)
      _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= caps[row.name], "resume_aux_form")


def _authenticate_resume_v1(root, review, code, plan_raw, boot_id, authority_descriptor, prior, context, stage):
  _require(compiler._json_bound(context) <= 8192, "resume_context_bound")
  keys = {"schema_version", "producer_commit", "producer_plan", "owner_project_root", "project_root",
    "retention_index", "operator", "retention", "prior_retention", "baseline", "boot_id",
    "consumer_commit", "consumer_plan", "pre_info"}
  _require(type(context) is dict and set(context) == keys and type(context["schema_version"]) is int and
    context["schema_version"] == 1 and context["producer_commit"] == RESUME_PRODUCER_COMMIT_V1 and
    context["consumer_commit"] == review["commit"] and root == RESUME_ROOT_V1 and
    context["project_root"] == str(root) and context["owner_project_root"] == str(RESUME_OWNER_ROOT_V1) and
    context["boot_id"] == boot_id and type(boot_id) is str and
    re.fullmatch("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", boot_id), "resume_context_roles")
  _resume_namespace_v1(root, stage)
  _resume_aux_v1()
  for key, cap in (("producer_plan", 40960), ("consumer_plan", 40960), ("operator", 32768), ("retention_index", 12288)):
    _resume_desc_v1(context[key], cap)
  _require(context["producer_plan"] == {"size_bytes": 25355,
    "sha256": "f024bfccb48e26be34b05b05fbc16082791b134f82967613177ad81a916d2d94",
    "git_blob": "4194c90dcfbc3dd4b44b71a4ce05c70192967397"} and
    context["consumer_plan"] == {"size_bytes": len(plan_raw), "sha256": _sha(plan_raw),
    "git_blob": hashlib.sha1(b"blob " + str(len(plan_raw)).encode() + b"\0" + plan_raw).hexdigest()}, "resume_plan_roles")
  baseline = context["baseline"]
  _require(type(baseline) is dict and set(baseline) == {"c_free_bytes", "ext4_used_bytes", "project_free_bytes",
    "fragment_bytes", "backing_device"} and all(type(n) is int and 0 <= n < 2**64 for n in baseline.values()) and
    baseline["fragment_bytes"] == 4096 and baseline["c_free_bytes"] >= 43620761600 and
    baseline["project_free_bytes"] >= 1207959552 and baseline["backing_device"] == root.stat().st_dev,
    "resume_baseline")
  _require(type(prior) is dict and set(prior) == {"git_observation", "native"} and
    component.canonical_json_v1(prior) == component.canonical_json_v1(context["prior_retention"]) and
    type(prior["git_observation"]) is dict and component.canonical_json_v1(prior["git_observation"].get("component")) ==
    component.canonical_json_v1(code[CODE_PATHS[1]]), "resume_prior_binding")
  _require(type(authority_descriptor) is dict and authority_descriptor.get("path") ==
    str(Path(str(root) + ".operator-originals") / "operator.authority.original.json"), "resume_authority_path")
  raw = _bound_descriptor(authority_descriptor, cap=8192)
  _require(_sha(raw) == review["evidence_sha256"], "resume_authority_binding")
  authority = _json(raw, 8192)
  helper = dict(context["operator"], path=str(REVIEW_REPO_ROOT_WINDOWS_V1 / RESUME_OPERATOR_V1))
  expected = {"schema_version": 1, "code_commit": review["commit"], "approval_reference": review["approval_reference"],
    "operator_sha256": helper["sha256"], "helper_code": {RESUME_OPERATOR_V1: helper},
    "context_sha256": _sha(component.canonical_json_v1(context)), "context": context, "external_approval_required": True}
  _require(component.canonical_json_v1(authority) == component.canonical_json_v1(expected), "resume_authority_shape")
  operator = context["operator"]
  source = _bound_descriptor({"path": str(component.REVIEW_REPO_ROOT_LINUX_V1 / RESUME_OPERATOR_V1),
    "size_bytes": operator["size_bytes"], "sha256": operator["sha256"]}, cap=32768)
  _require(hashlib.sha1(b"blob " + str(len(source)).encode() + b"\0" + source).hexdigest() == operator["git_blob"],
    "resume_operator_git")
  _resume_info_binding_v1(context)
  try:
    fresh = component.verify_resume_retention_v1(component.REVIEW_REPO_ROOT_LINUX_V1,
      git_observation=prior["git_observation"], index_descriptor=context["retention_index"])
    _require(component.canonical_json_v1(fresh) == component.canonical_json_v1(context["retention"]), "resume_retention_drift")
    quote = component.resume_code_forms_quote_v1(component.REVIEW_REPO_ROOT_LINUX_V1, code=code,
      plan=context["consumer_plan"], operator=operator, index_descriptor=context["retention_index"])
  except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError) as error:
    raise Gate2Refusal("resume_retention_unavailable") from error
  _require(type(quote) is int and 0 <= quote <= component.RESUME_CODE_FORMS_V1 == 1032192, "resume_source_forms_bound")
  return quote


def _resume_originals_v1(context, review, p0_descriptor):
  from tests.fixtures import accepted_policy_fixture_compiler_gate2_resume_v1 as resume
  from tests.fixtures import accepted_policy_fixture_compiler_gate2_p0_v1 as p0
  aux = Path(str(RESUME_ROOT_V1) + ".operator-originals")
  bodies = {key: _read(aux / name, 4096) for key, name in
    (("command", "operator.command.original.json"), ("p0_return", "p0.return.original.json"))}
  command = {"schema_version": 1, "code_commit": review["commit"], "approval_reference": review["approval_reference"],
    "operator_sha256": context["operator"]["sha256"], "phase_program_sha256": resume.native_program_hashes_v1()}
  _require(component.canonical_json_v1(_json(bodies["command"], 4096)) == component.canonical_json_v1(command),
    "resume_command_binding")
  returned = _json(bodies["p0_return"], 4096)
  expected = {"code_commit": review["commit"], "accepted": True, "causes": [], "controlled": False,
    "physical_acceptance": False, "reviewed_operator_sha256": context["operator"]["sha256"],
    "kernel_preemption_claimed": False, "external_invocation_status_and_eof_required": True}
  _require(type(returned) is dict and set(returned) == set(expected) | {"completion_record"} and
    all(type(returned[k]) is type(v) and returned[k] == v for k, v in expected.items()), "resume_p0_return")
  record = returned["completion_record"]
  _require(type(record) is dict and set(record) == {"relative_path", "encoded_bytes", "sha256", "claims_self_persistence",
    "write_proof"} and record["relative_path"] == "p0-completion.v1.json" and record["claims_self_persistence"] is False and
    type(record["encoded_bytes"]) is int and record["encoded_bytes"] == p0_descriptor["size_bytes"] and
    record["sha256"] == p0_descriptor["sha256"], "resume_p0_completion")
  try:
    p0._originals_proof(record["write_proof"], _bound_descriptor(p0_descriptor, root=RESUME_ROOT_V1, cap=4096))
  except ValueError as error:
    raise Gate2Refusal("resume_p0_write_proof") from error
  return {key: _descriptor(aux / ("operator.command.original.json" if key == "command" else "p0.return.original.json"), raw)
    for key, raw in bodies.items()}


def build_packet_v1(*, project_root, review, physical_plan_descriptor, code, evidence, p0_descriptor,
  boot_id, initial_charged_bytes, initial_measurement,
  operator_authority_descriptor, prior_retention, resume_context=None, _stage=None):
  root = Path(project_root)
  _require(root.is_absolute() and root.resolve(strict=True) == root, "packet_root")
  review = component._review(review)
  plan_raw = _bound_descriptor(physical_plan_descriptor, cap=65536)
  _verify_code(root if resume_context is None else component.REVIEW_REPO_ROOT_LINUX_V1, code)
  _require(type(boot_id) is str and 1 <= len(boot_id) <= 64 and
    type(initial_charged_bytes) is int and 11890688 <= initial_charged_bytes < SEAL_BYTES, "packet_physical")
  interval_charge_v1(initial_measurement, initial_measurement, retained_bytes=0)
  if resume_context is not None:
    current_quote = _authenticate_resume_v1(root, review, code, plan_raw, boot_id,
      operator_authority_descriptor, prior_retention, resume_context, _stage)
    _require(type(initial_charged_bytes) is int and initial_charged_bytes == RESUME_INITIAL_CHARGE_V1,
      "resume_initial_charge")
    _require(p0_descriptor.get("path") == str(root / "p0/p0-completion.v1.json"), "resume_p0_path")
    _require(type(evidence) is dict and set(evidence)==set(EVIDENCE_NAMES) and all(
      type(evidence[k]) is dict and evidence[k].get("path")==str(p) for k,p in _resume_evidence_paths_v1().items()),
      "resume_evidence_paths")
    _require(physical_plan_descriptor["path"]==str(component.REVIEW_REPO_ROOT_LINUX_V1 /
      (component.RETENTION_INDEX_REL_V1.rsplit("/",1)[0]+"/component-admission-plan.v8.md")),"resume_plan_path")
    admitted = _authenticate_evidence(evidence, dict(review, commit=RESUME_PRODUCER_COMMIT_V1),
      resume_context["producer_plan"]["sha256"])
    account = admitted["accounting"]
    _require(account["physical_charge_bytes"] + account["reserved_control_bytes"] +
      account["reserved_rounding_bytes"] + account["reserved_metadata_bytes"] <= component.ACTIVE_F2_LIMIT_V1,
      "resume_active_f2_bound")
  else:
    current_quote, admitted = _legacy_packet_bindings_v1(root, review, code, plan_raw, boot_id,
      operator_authority_descriptor, prior_retention, evidence, initial_measurement, initial_charged_bytes)
  _validate_p0(p0_descriptor, root, review["commit"], boot_id)
  proofs = _proof_envelopes(evidence)
  seed = component.component_seed_v1(review=review,
    bindings={"host_sha256": code[CODE_PATHS[2]]["sha256"], "publisher_sha256": code[CODE_PATHS[3]]["sha256"],
    "profile_sha256": code[CODE_PATHS[4]]["sha256"]},
    engine={"driver": EXPECTED["driver"], "cgroup_driver": EXPECTED["cgroup_driver"],
    "security_options": EXPECTED["security_options"], "runtimes_sha256": EXPECTED["runtimes_sha256"]},
    provider={"rootfs_sha256": EXPECTED["rootfs_sha256"], "size_bytes": EXPECTED["provider_size"]},
    environment_keys=admitted["environment_keys"], mounts_sha256=MOUNTS_SHA256,
    proofs={kind: _sha(component.canonical_json_v1(value)) for kind, value in proofs.items()})
  seed_raw = component.canonical_json_v1(seed)
  _require(len(seed_raw) <= 4096, "seed_bound")
  packet = {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_gate2_packet_v1",
    "project_root": str(root), "code_commit": review["commit"], "code_review": review,
    "physical_plan": physical_plan_descriptor, "code": code, "source_sha256": component.SOURCE_SHA256,
    "evidence": evidence, "proofs": proofs, "seed": seed, "seed_sha256": _sha(seed_raw), "p0": p0_descriptor,
    "boot_id": boot_id, "initial_charged_bytes": initial_charged_bytes, "initial_measurement": initial_measurement,
    "operator_authority": operator_authority_descriptor, "prior_retention": prior_retention,
    "current_code_forms_quote_bytes": current_quote}
  if resume_context is not None:
    packet["resume_context"] = resume_context
    packet["resume_originals"] = _resume_originals_v1(resume_context, review, p0_descriptor)
  _require(compiler._json_bound(packet) <= (PACKET_LIMIT if resume_context is None else RESUME_PACKET_LIMIT_V1), "packet_bound")
  _require(sum(desc["size_bytes"] for desc in code.values()) + len(component.canonical_json_v1(packet)) +
    len(plan_raw) + len(seed_raw) + (0 if resume_context is None else resume_context["operator"]["size_bytes"])
    <= 640 * 1024, "code_packet_allocation")
  return packet


def _legacy_packet_bindings_v1(root, review, code, plan_raw, boot_id, operator_authority_descriptor,
  prior_retention, evidence, initial_measurement, initial_charged_bytes):
  _authenticate_prior_retention_v1(root, review, code, boot_id, operator_authority_descriptor, prior_retention)
  try:
    current_quote = component.current_code_forms_quote_v1(component.REVIEW_REPO_ROOT_LINUX_V1,
      code=code, plan={"size_bytes": len(plan_raw), "sha256": _sha(plan_raw),
      "git_blob": hashlib.sha1(b"blob " + str(len(plan_raw)).encode("ascii") + b"\0" + plan_raw).hexdigest()})
  except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError) as error:
    raise Gate2Refusal("current_code_forms_unavailable") from error
  _require(type(current_quote) is int and 0 <= current_quote <= component.CURRENT_CODE_FORMS_V1,
    "current_code_forms_bound")
  admitted = _authenticate_evidence(evidence, review, _sha(plan_raw))
  accounting = admitted["accounting"]
  f2_tail = accounting["reserved_control_bytes"] + accounting["reserved_rounding_bytes"] + accounting["reserved_metadata_bytes"]
  _require(all(type(value) is int and value >= 0 for value in (accounting["physical_charge_bytes"], f2_tail)), "initial_f2_charge")
  gap = interval_charge_v1(accounting["last"], initial_measurement, retained_bytes=0)
  _require(accounting["physical_charge_bytes"] + f2_tail <= component.ACTIVE_F2_LIMIT_V1, "active_f2_bound")
  minimum = (11890688 + 2 * 1048576 + accounting["physical_charge_bytes"] + f2_tail
    + max(0, gap - f2_tail - 1048576) + component.PRIOR_CARRY_BYTES_V1
    + component.CURRENT_CODE_FORMS_V1)
  _require(initial_charged_bytes >= minimum, "initial_charge_omitted_forms")
  return current_quote, admitted


def validate_packet_v1(*, project_root, packet_descriptor, expected_packet_sha256, expected_code_commit, _stage=None):
  _require(_sha_shape(expected_packet_sha256) and type(expected_code_commit) is str and
    re.fullmatch("[0-9a-f]{40}", expected_code_commit) is not None, "external_packet_authority")
  root = Path(project_root)
  cap = RESUME_PACKET_LIMIT_V1 if root == RESUME_ROOT_V1 else PACKET_LIMIT
  raw = _bound_descriptor(packet_descriptor, root=root, cap=cap)
  _require(_sha(raw) == expected_packet_sha256, "external_packet_hash")
  packet = _json(raw, PACKET_LIMIT)
  _require(packet.get("code_commit") == expected_code_commit and packet.get("project_root") == str(root), "external_commit_root")
  rebuilt = build_packet_v1(project_root=root, review=packet.get("code_review"),
    physical_plan_descriptor=packet.get("physical_plan"), code=packet.get("code"), evidence=packet.get("evidence"),
    p0_descriptor=packet.get("p0"),
    boot_id=packet.get("boot_id"), initial_charged_bytes=packet.get("initial_charged_bytes"),
    initial_measurement=packet.get("initial_measurement"),
    operator_authority_descriptor=packet.get("operator_authority"), prior_retention=packet.get("prior_retention"),
    resume_context=packet.get("resume_context"), _stage=_stage)
  _require(type(packet.get("current_code_forms_quote_bytes")) is int and
    packet == rebuilt, "packet_content_drift")
  return packet


def validate_resume_retention_index_v1(index, old_rows):
  from tests.fixtures import accepted_policy_fixture_compiler_gate2_resume_v1 as r
  slots = [row['path'] for row in old_rows] + [r.OPERATOR]
  r.need(type(index) is dict and index.get('schema')=='vast_gate2_p0_465_retention_v1'
    and index.get('physical_acceptance') is False and index.get('source_slots')==slots
    and index.get('source_form_slots')==[0,1,6,7,10,13]
    and index.get('outside_helper_slots')==[11,12]
    and index.get('fixed_unchanged_slots')==[2,3,4,5,8,9], 'retention_index_slots')
  rows = index.get('source_versions')
  r.need(type(rows) is list and 21<=len(rows)<=40,'retention_versions')
  identities = set()
  for row in rows:
    r.need(type(row) is list and len(row)==4 and type(row[0]) is int and 0<=row[0]<14
      and type(row[1]) is str and re.fullmatch('[0-9a-f]{40}',row[1])
      and type(row[2]) is int and 0<row[2]<=262144 and type(row[3]) is str
      and re.fullmatch('[0-9a-f]{64}',row[3]) and (row[0],row[1]) not in identities,'retention_version')
    identities.add((row[0],row[1]))
  history = index.get('historical_bindings')
  r.need(type(history) is list and len(history)==4 and [row[0] for row in history]==
    ['c75','producer465','p0fix','planning'],'retention_history')
  for _, selected in history:
    r.need(type(selected) is list and len(selected)==13 and all(type(n) is int and 0<=n<len(rows)
      and rows[n][0]==slot for slot,n in enumerate(selected)),'retention_history_binding')
  r.need(all(rows[n][1:]==[old['git_blob'],old['size_bytes'],old['sha256']]
    for n,old in zip(history[0][1],old_rows)), 'retention_c75_binding')
  current = index.get('current_bindings')
  r.need(type(current) is list and len(current)==14 and all(n is None or type(n) is int
    and 0<=n<len(rows) and rows[n][0]==slot for slot,n in enumerate(current)), 'retention_current')
  for slot in (2,3,4,5,8,9,11,12):
    selected = history[1 if slot in (11,12) else 0][1][slot]
    r.need(current[slot]==selected and all(row==rows[selected] or row==rows[history[0][1][slot]]
      for row in rows if row[0]==slot),'retention_unfunded_version')
  r.need(index.get('roots')=={'owner':r.OWNER.as_posix(),'child':r.ROOT.as_posix(),'aux':r.AUX.as_posix()}
    and index.get('roles')=={'c75':'c75ad950ee542621a365725db627fdd03d2363e8',
     'producer465':r.PRODUCER,'p0fix':'bf2c3df73470c198eb71772efa473e5766bcc122',
     'planning':'69c2c35f3d51c8d4ef047e7050fe82bfc3b79eae'},'retention_roots_roles')
  refs=index.get('refs')
  r.need(type(refs) is list and len(refs)==6 and [row[0] for row in refs]==
    ['c75_index','465_verification','bf2_verification','diagnostic','manifest','writer']
    and refs[3][2:]==[8645,r.DIAGNOSTIC_SHA] and refs[4][2:]==[11132,r.MANIFEST_SHA], 'retention_refs')

def resume_native_entry_v1(phase, x):
  from tests.fixtures import accepted_policy_fixture_compiler_gate2_resume_v1 as r
  try:
    _require(phase in ('PRE','PACKET','FINAL'),'resume_native_phase')
    boot=lambda:compiler._compiler_proc_read_v1('/proc/sys/kernel/random/boot_id',64).decode('ascii').strip()
    if phase=='PRE':
      ready={'linux_ready_ns':time.monotonic_ns(),'boot_id':boot()}
      raw=r.canonical(ready)+b'\n';n=os.write(1,raw)
      if n!=len(raw): raise Gate2Refusal('native_ready_short',{'written_bytes':n})
      r.need(select.select([0],[],[],15)[0],'ack_missing')
      ack=r.decode(sys.stdin.buffer.readline(1025),1024)
      deadline=min(ack['global_deadline_ns'],ack['phase_deadline_ns'])
      r.need(time.monotonic_ns()<deadline and ack['boot_id']==boot()==ready['boot_id'],'ack_late_boot')
      result=resume_pre_v1(code={p:x['current'][p] for p in CODE_PATHS},plan=x['current'][r.PLAN],
        operator=x['current'][r.OPERATOR],index_descriptor=x['index'],git_observation=x['git_observation'],
        absolute_deadline_ns=deadline)
    else:
      deadline=min(x['global_deadline_ns'],x['phase_deadline_ns'])
      r.need(time.monotonic_ns()<deadline and boot()==x['context']['boot_id'],'native_late_boot')
      if phase=='PACKET':
        result=resume_packet_v1(context=x['context'],code={p:x['current'][p] for p in CODE_PATHS},
          review=x['review'],authority_descriptor=x['authority'],p0_descriptor=x['p0'],absolute_deadline_ns=deadline)
      else:
        result=resume_final_v1(context=x['context'],packet_descriptor=x['packet'],
          events_descriptor=x['events'],absolute_deadline_ns=deadline)
    if not time.monotonic_ns()<deadline or compiler._json_bound(result)>7168:
      raise Gate2Refusal('native_result_bound_deadline',result)
    raw=r.canonical(result)+b'\n';n=os.write(1,raw)
    if n!=len(raw): raise Gate2Refusal('native_result_short',{'written_bytes':n})
    r.need(time.monotonic_ns()<deadline,'native_emit_late')
  except BaseException as error:
    try: os.write(2,native_failure_bytes_v1(error))
    except OSError: pass
    raise SystemExit(1) from None


def resume_terminal_v1(*, error=None, result=None):
  value = {'completed':error is None, 'physical_acceptance':False,
      'external_terminal_and_packet_review_required':True,'native_raw_originals_retained':0}
  if error is None:
    value.update(result or {})
  else:
    facts = getattr(error, 'facts', {})
    raw = None
    try:
      _require(compiler._json_bound(facts)<=CONTROL_LIMIT,'terminal_facts_bound')
      raw=component.canonical_json_v1(facts)
    except (Gate2Refusal,ValueError,TypeError,RecursionError,OverflowError): pass
    causes, known = [str(error)[:64]], []
    keys = {'pid','returncode','stdout_eof','stderr_eof','unknown_closure','close_completed',
        'stdout_bytes','stderr_bytes','stdout_sha256','stderr_sha256','stdout_prefix_base64','stderr_prefix_base64',
        'eof_stdout','eof_stderr','forced_parent_termination','write_extent_unknown',
        'request_write_extent_unknown','reply_write_extent_unknown',
        'fsync_completed','extent_unknown','written_bytes','late','completed','linux_child_closure','stdin_closed','stdin_extent_unknown'}
    def visit(node, path='', depth=0):
      if depth > 7 or len(known) >= 16:
        return
      if type(node) is dict:
        for role in ('control_record','completion_record'):
          if type(node.get(role)) is dict: visit(node[role],path+'/'+role,depth+1)
        for count,(key,item) in enumerate(node.items()):
          if count>=24: break
          if key in ('control_record','completion_record') or key=='late' and path.endswith('/write_proof'): continue
          if key == 'secondary' or key == 'causes':
            if type(item) is list:
              for cause in item[:5]:
                if type(cause) is str and cause[:48] not in causes and len(causes) < 5:
                  causes.append(cause[:48])
          if key in keys and (item is None or type(item) in (bool,str) or type(item) is int and -2**64<=item<2**64) and len(known) < 16:
            known.append({'path':(path+'/'+key)[-48:], 'value':item[:64] if type(item) is str else item})
          elif type(item) in (dict,list):
            visit(item, path+'/'+(key[:48] if type(key) is str else '?'), depth+1)
      elif type(node) is list:
        for i, item in enumerate(node[:4]): visit(item,path+'/'+str(i),depth+1)
    visit(facts)
    value.update(causes=[c.encode('ascii','backslashreplace').decode()[:64] for c in causes],
      cause_remainder_unknown=True, known=known, omitted_or_unknown=True)
    if raw is None: value['facts_unknown']=True
    else: value.update(facts_bytes=len(raw),facts_sha256=_sha(raw),prefix_base64=base64.b64encode(raw[:48]).decode('ascii'))
    original_count=len(known)
    while len(component.canonical_json_v1(value))+1>2048 and known:
      known.pop();value['known_omitted']=original_count-len(known)
  raw = component.canonical_json_v1(value)
  _require(len(raw) + 1 <= 2048, 'terminal_bound')
  return raw



def _resume_check_v1(deadline):
  _require(sys.version_info[:3] == (3, 12, 3) and os.name=="posix" and
    (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) == (1000, 1000, 1000, 1000), "resume_actor")
  _require(type(deadline) is int and time.monotonic_ns() < deadline, "resume_phase_deadline")


def _resume_measure_v1():
  c, ext = os.statvfs("/mnt/c"), os.statvfs(RESUME_OWNER_ROOT_V1)
  _require(c.f_frsize == ext.f_frsize == 4096 and RESUME_OWNER_ROOT_V1.stat().st_dev == Path("/").stat().st_dev,
    "resume_backing")
  value = {"c_free_bytes": c.f_bavail * c.f_frsize, "ext4_used_bytes": (ext.f_blocks - ext.f_bfree) * ext.f_frsize,
    "project_free_bytes": ext.f_bavail * ext.f_frsize, "fragment_bytes": 4096,
    "backing_device": RESUME_OWNER_ROOT_V1.stat().st_dev}
  _require(value["c_free_bytes"] >= 43620761600 and value["project_free_bytes"] >= 1207959552, "resume_floor")
  return value


def resume_pre_v1(*, code, plan, operator, index_descriptor, git_observation, absolute_deadline_ns):
  _resume_check_v1(absolute_deadline_ns)
  baseline = _resume_measure_v1()
  _require(not os.path.lexists(RESUME_ROOT_V1) and not os.path.lexists(Path(str(RESUME_ROOT_V1) + ".operator-originals")),
    "resume_scope_exists")
  boot = compiler._compiler_proc_read_v1("/proc/sys/kernel/random/boot_id", 64).decode("ascii").strip()
  _require(re.fullmatch("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", boot), "resume_boot")
  retention = component.verify_resume_retention_v1(component.REVIEW_REPO_ROOT_LINUX_V1,
    git_observation=git_observation, index_descriptor=index_descriptor)
  _resume_check_v1(absolute_deadline_ns)
  quote = component.resume_code_forms_quote_v1(component.REVIEW_REPO_ROOT_LINUX_V1,
    code=code, plan=plan, operator=operator, index_descriptor=index_descriptor)
  _require(type(quote) is int and 0 <= quote <= component.RESUME_CODE_FORMS_V1 == 1032192, "resume_source_forms_bound")
  _resume_check_v1(absolute_deadline_ns)
  reserve_v1(charged=RESUME_INITIAL_CHARGE_V1, liability=507510784, c_free_bytes=baseline["c_free_bytes"])
  RESUME_ROOT_V1.mkdir(mode=0o700)
  aux = Path(str(RESUME_ROOT_V1) + ".operator-originals")
  _resume_check_v1(absolute_deadline_ns)
  aux.mkdir(mode=0o700)
  from tests.fixtures import accepted_policy_fixture_compiler_gate2_d_v1 as d
  client = d._DInfoClientV1(aux, absolute_deadline_ns)
  try:
    info = client.request("GET", "/info")
    pre_info = resume_info_v1(info=info, rpc_facts=client.facts,
      request_raw=_read(aux / "RPC01.request.original", 16384), reply_raw=_read(aux / "RPC01.reply.original", 16384))
    retention = component.verify_resume_retention_v1(component.REVIEW_REPO_ROOT_LINUX_V1,
      git_observation=git_observation, index_descriptor=index_descriptor)
    _resume_check_v1(absolute_deadline_ns)
    _resume_measure_v1()
    _require(compiler._compiler_proc_read_v1("/proc/sys/kernel/random/boot_id", 64).decode("ascii").strip() == boot,
      "resume_boot_drift")
    _resume_check_v1(absolute_deadline_ns)
    return {"baseline": baseline, "boot_id": boot, "retention": retention, "pre_info": pre_info,
      "rpc_facts": _rpc_json_facts_v1(client.facts), "native_pid": os.getpid(), "source_quote_bytes": quote}
  except BaseException as error:
    raise Gate2Refusal("resume_pre_stopped", {"cause": getattr(error,"cause",type(error).__name__),"causes":getattr(error,"causes",[]),
      "failure_facts": getattr(error,"facts",{}), "baseline": baseline, "boot_id": boot,
      "rpc_facts": client.facts}) from error


def _resume_allocated_v1(root, limit):
  pending, total, count, seen = [root], 0, 0, set()
  device = RESUME_OWNER_ROOT_V1.stat().st_dev
  while pending:
    path = pending.pop()
    value = path.lstat()
    count += 1
    _require(count <= 128 and value.st_dev == device and (value.st_dev, value.st_ino) not in seen and
      path.resolve(strict=True) == path and type(value.st_blocks) is int and value.st_blocks >= 0,
      "resume_allocation_unknown")
    seen.add((value.st_dev, value.st_ino))
    _require(stat.S_ISDIR(value.st_mode) or stat.S_ISREG(value.st_mode) and value.st_nlink == 1, "resume_allocation_kind")
    total += max(value.st_blocks * 512, (value.st_size + 4095) // 4096 * 4096) + 256
    _require(total <= limit, "resume_allocation_bound")
    if stat.S_ISDIR(value.st_mode):
      with os.scandir(path) as entries:
        for entry in entries:
          _require(count + len(pending) < 128, "resume_allocation_entries")
          pending.append(Path(entry.path))
  return total


def _resume_evidence_paths_v1():
  b = Path("/home/s-a-balashov/work/vast-fixture-compiler-component-8c08cd30f2355a26b2e7a31b53e6f268acafda29-01")
  aux, f2 = Path(str(RESUME_OWNER_ROOT_V1) + ".operator-originals"), Path(str(RESUME_OWNER_ROOT_V1) + ".f2")
  return {"b1_result": b / "outputs/B1/probe.result.original.json", "b1_report": b / "outputs/B1/compiler.stdout.original",
    "b2_result": b / "outputs/B2/probe.result.original.json", "b2_report": b / "outputs/B2/compiler.stdout.original",
    "b3_result": b / "outputs/B3/probe.result.original.json", "b2_manifest": b / "runs/B2.originals.sha256",
    "b2_index": aux / "b2.corrected-index.v1.json", "f2_supplement": f2 / "f2.supplement.v1.json",
    "f2_index": f2 / "f2.originals.v1.json", "f2_accounting": f2 / "f2.final-accounting.v1.json"}


def resume_packet_v1(*, context, code, review, authority_descriptor, p0_descriptor, absolute_deadline_ns):
  _resume_check_v1(absolute_deadline_ns)
  paths = _resume_evidence_paths_v1()
  evidence = {}
  for key, path in paths.items():
    _resume_check_v1(absolute_deadline_ns)
    evidence[key] = _descriptor(path, _read(path, component.F2_FOOTER_LIMIT_V1 if key == "f2_accounting" else 1048576))
  plan = component.REVIEW_REPO_ROOT_LINUX_V1 / (component.RETENTION_INDEX_REL_V1.rsplit("/", 1)[0] + "/component-admission-plan.v8.md")
  plan_desc = _descriptor(plan, _read(plan, 40960))
  packet = build_packet_v1(project_root=RESUME_ROOT_V1, review=review, physical_plan_descriptor=plan_desc,
    code=code, evidence=evidence, p0_descriptor=p0_descriptor, boot_id=context["boot_id"],
    initial_charged_bytes=RESUME_INITIAL_CHARGE_V1, initial_measurement=_resume_measure_v1(),
    operator_authority_descriptor=authority_descriptor, prior_retention=context["prior_retention"], resume_context=context)
  written = write_record_v1(RESUME_ROOT_V1 / "gate2.packet.original.json", packet, cap=RESUME_PACKET_LIMIT_V1,
    absolute_deadline_ns=absolute_deadline_ns, return_facts=True)
  _resume_check_v1(absolute_deadline_ns)
  return {"packet": written["descriptor"], "packet_write_facts": written["write_facts"], "initial_charged_bytes": RESUME_INITIAL_CHARGE_V1, "native_pid": os.getpid()}


def resume_final_v1(*, context, packet_descriptor, events_descriptor, absolute_deadline_ns):
  _resume_check_v1(absolute_deadline_ns)
  packet = validate_packet_v1(project_root=RESUME_ROOT_V1, packet_descriptor=packet_descriptor,
    expected_packet_sha256=packet_descriptor["sha256"], expected_code_commit=context["consumer_commit"])
  _require(component.canonical_json_v1(packet["resume_context"]) == component.canonical_json_v1(context), "resume_final_context")
  aux = Path(str(RESUME_ROOT_V1) + ".operator-originals")
  _require(events_descriptor.get("path") == str(aux / "resume.events.original.json"), "resume_events_path")
  _bound_descriptor(events_descriptor, cap=8192)
  _require(compiler._compiler_proc_read_v1("/proc/sys/kernel/random/boot_id", 64).decode("ascii").strip() == context["boot_id"],
    "resume_boot_drift")
  fresh = component.verify_resume_retention_v1(component.REVIEW_REPO_ROOT_LINUX_V1,
    git_observation=context["prior_retention"]["git_observation"], index_descriptor=context["retention_index"])
  _resume_check_v1(absolute_deadline_ns)
  _resume_aux_v1()
  growth = fresh["native"]["parent_growth_bytes"]
  current, controls = _resume_allocated_v1(RESUME_ROOT_V1, 1048576), _resume_allocated_v1(aux, 50944)
  future = 32768 + 12544
  native, outside = 586240 + current + growth + 12544, 399872 + 32768 + controls + 32768
  _require(native <= 1048576 and outside <= 524288, "resume_forms_bound")
  measured = _resume_measure_v1()
  charge = interval_charge_v1(context["baseline"], measured, retained_bytes=current + controls + growth) + future
  _require(charge <= 2650112 and 5345280 + charge <= component.ACTIVE_F2_LIMIT_V1, "resume_interval_bound")
  _resume_check_v1(absolute_deadline_ns)
  return {"final_measurement": measured, "fresh_interval_N": charge, "active_f2_debit": 5345280 + charge,
    "native_bytes": native, "outside_bytes": outside, "outstanding_tail_bytes": future, "native_pid": os.getpid(),
    "historical_closing_meter_available": False, "physical_acceptance": False}


def capture_guard_v1(kind, *, output_dir, absolute_deadline_ns, stdout_limit=None, stderr_limit=4096, record_original=True, _phase_prefix=None):
  """Capture one of three fixed read-only commands, with one absolute budget."""
  recipes = {
    "dmesg": (["/usr/bin/dmesg", "--color=never"], 192 * 1024),
    "journal": (["/usr/bin/journalctl", "--disk-usage"], 512),
    "gpu": (["/usr/lib/wsl/lib/nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"], 4096),
  }
  _require(kind in recipes and (type(_phase_prefix) is str and _phase_prefix in ("before", "after") or
    _phase_prefix is None), "guard_kind_phase")
  file_prefix = "" if _phase_prefix is None else _phase_prefix + "."
  argv, maximum = recipes[kind]
  stdout_limit = maximum if stdout_limit is None else stdout_limit
  _require(type(stdout_limit) is int and 0 < stdout_limit <= maximum and
    type(stderr_limit) is int and 0 <= stderr_limit <= 4096 and type(record_original) is bool, "guard_capture_bound")
  output = Path(output_dir)
  _require(output.is_absolute() and output.resolve(strict=True) == output and output.is_dir(), "guard_output")
  start = time.monotonic_ns()
  _require(type(absolute_deadline_ns) is int and absolute_deadline_ns - start > 300_000_000, "guard_deadline")
  work_end, term_end = absolute_deadline_ns - 200_000_000, absolute_deadline_ns - 100_000_000
  facts = {"argv": argv, "pid": None, "returncode": None, "stdout_eof": False, "stderr_eof": False,
    "persisted": False, "closed": False, "forced": False, "causes": [], "stdout": None, "stderr": None, "files": {}}
  streams, files, kept, observed, digests = {}, {}, {}, {}, {}
  process = None
  def fail(cause):
    if cause not in facts["causes"]:
      facts["causes"].append(cause)
  def within_deadline():
    if time.monotonic_ns() >= absolute_deadline_ns:
      fail("guard_deadline")
      return False
    return True
  try:
    for name in ("stdout", "stderr"):
      _require(within_deadline(), "guard_deadline")
      files[name] = (output / (file_prefix + kind + "." + name + ".original")).open("xb", buffering=0)
      kept[name], observed[name], digests[name] = 0, 0, hashlib.sha256()
      facts["files"][name] = {"open_completed": True, "write_failed": False, "write_extent_unknown": False,
        "written_bytes": 0, "persisted_bytes": 0, "flush_completed": False, "fsync_completed": False, "close_completed": False}
    _require(within_deadline(), "guard_deadline")
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
      start_new_session=True, close_fds=True, bufsize=0, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"})
    facts["pid"] = process.pid
    _require(type(process.pid) is int and process.pid > 1, "guard_pid")
    for name in ("stdout", "stderr"):
      streams[name] = getattr(process, name)
      os.set_blocking(streams[name].fileno(), False)
    active = dict(streams)
    while active:
      now = time.monotonic_ns()
      if now >= work_end:
        fail("guard_deadline")
        break
      ready, _, _ = select.select(list(active.values()), [], [], min(.02, (work_end - now) / 1e9))
      for name, stream in list(active.items()):
        if stream not in ready:
          continue
        cap = stdout_limit if name == "stdout" else stderr_limit
        try:
          raw = stream.read(min(65536, cap - kept[name] + 1))
        except BlockingIOError:
          continue
        _require(type(raw) is bytes, "guard_read_contract")
        if not raw:
          facts[name + "_eof"] = True
          del active[name]
          continue
        observed[name] += len(raw)
        prefix = raw[:cap - kept[name]]
        _require(within_deadline(), "guard_deadline")
        try:
          written = files[name].write(prefix)
        except (OSError, ValueError):
          facts[name + "_write_extent_unknown"] = True
          facts["files"][name].update(write_failed=True, write_extent_unknown=True)
          fail("guard_" + name + "_write")
          raise
        if type(written) is not int or not 0 <= written <= len(prefix):
          facts[name + "_write_extent_unknown"] = True
          facts["files"][name].update(write_failed=True, write_extent_unknown=True)
          raise Gate2Refusal("guard_write_contract")
        digests[name].update(prefix[:written])
        kept[name] += written
        facts["files"][name]["written_bytes"] = kept[name]
        if written != len(prefix):
          facts["files"][name]["write_failed"] = True
          fail("guard_" + name + "_short_write")
        _require(written == len(prefix), "guard_short_write")
        if len(raw) > len(prefix):
          fail("guard_" + name + "_overflow")
      if facts["causes"]:
        break
    if not facts["causes"] and process.poll() is None and time.monotonic_ns() < work_end:
      try:
        process.wait(timeout=max(0, work_end - time.monotonic_ns()) / 1e9)
      except subprocess.TimeoutExpired:
        fail("guard_deadline")
  except (OSError, ValueError, TypeError, Gate2Refusal) as error:
    fail(error.cause if isinstance(error, Gate2Refusal) else "guard_" + type(error).__name__)
  finally:
    if process is not None:
      for label, until in (("TERM", term_end), ("KILL", absolute_deadline_ns)):
        try:
          if process.poll() is not None:
            break
          facts["forced"] = True
          fail("guard_forced")
          if time.monotonic_ns() >= until:
            fail("guard_closure_unknown")
            continue
          facts[label.lower() + "_attempted"] = True
          try:
            os.killpg(process.pid, signal.SIGTERM if label == "TERM" else signal.SIGKILL)
          except ProcessLookupError:
            pass
          try:
            process.wait(timeout=max(0, until - time.monotonic_ns()) / 1e9)
          except subprocess.TimeoutExpired:
            pass
        except (OSError, ValueError):
          fail("guard_containment_unknown")
      facts["returncode"] = process.poll()
      if type(facts["returncode"]) is not int:
        fail("guard_closure_unknown")
      elif facts["returncode"] != 0:
        fail("guard_status")
    pipe_closed = True
    for stream in streams.values():
      try:
        stream.close()
      except OSError:
        pipe_closed = False
        fail("guard_pipe_close")
    persisted, closed = True, pipe_closed
    for name, file in files.items():
      row = facts["files"][name]
      if within_deadline():
        try:
          file.flush()
          row["flush_completed"] = True
        except OSError:
          fail("guard_" + name + "_flush")
      if within_deadline():
        try:
          os.fsync(file.fileno())
          row["fsync_completed"] = True
        except OSError:
          fail("guard_" + name + "_fsync")
      try:
        file.close()
        row["close_completed"] = True
      except OSError:
        closed = False
        fail("guard_" + name + "_close")
      unknown = facts.get(name + "_write_extent_unknown", False)
      facts[name + "_observed_bytes"] = observed[name]
      facts[name + "_confirmed_prefix_sha256"] = digests[name].hexdigest()
      facts[name] = {"path": str(output / (file_prefix + kind + "." + name + ".original")),
        "size_bytes": None if unknown else kept[name], "sha256": None if unknown else digests[name].hexdigest()}
      file_persisted = not row["write_failed"] and row["flush_completed"] and row["fsync_completed"] and not unknown
      if file_persisted:
        row["persisted_bytes"] = kept[name]
      persisted = persisted and file_persisted
    facts["persisted"], facts["closed"] = persisted, closed
    if within_deadline():
      try:
        compiler._compiler_directory_sync_v1(output)
      except OSError:
        facts["persisted"] = False
        fail("guard_directory_sync")
    else:
      facts["persisted"] = False
  if not facts["stdout_eof"] or not facts["stderr_eof"]:
    fail("guard_eof_unknown")
  if time.monotonic_ns() >= absolute_deadline_ns:
    fail("guard_deadline")
  if record_original:
    try:
      write_record_v1(output / (file_prefix + kind + ".capture.original.json"), facts, cap=8192, absolute_deadline_ns=absolute_deadline_ns)
    except (Gate2Refusal, OSError, ValueError) as error:
      fail("guard_record_incomplete")
      facts["record_failure"] = getattr(error, "facts", {})
      raise Gate2Refusal("guard_record_incomplete", facts)
  if facts["causes"]:
    raise Gate2Refusal("guard_refused", facts)
  return facts


def observe_identity_v1(*, output_dir, expected_cids, absolute_deadline_ns, rpc_timeout_ns=1_000_000_000):
  _require(type(expected_cids) is list and 3 <= len(expected_cids) <= 9 and
    len(set(expected_cids)) == len(expected_cids) and all(type(cid) is str and
    re.fullmatch("[0-9a-f]{64}", cid) for cid in expected_cids) and set(B_CIDS) <= set(expected_cids), "guard_expected_cids")
  _require(type(rpc_timeout_ns) is int and 0 < rpc_timeout_ns <= 5_000_000_000, "guard_rpc_deadline")
  client = compiler._DockerClientV1(Path(output_dir), absolute_deadline_ns)
  client.RPC_LIMIT = 4
  def get(path):
    now = time.monotonic_ns()
    _require(now < absolute_deadline_ns, "guard_deadline")
    return client.request("GET", path, deadline_ns=min(absolute_deadline_ns, now + rpc_timeout_ns))
  version, info = get("/version"), get("/info")
  image = get("/images/" + compiler.PROVIDER_ID + "/json?manifests=1")
  containers = get("/containers/json?all=1")
  _require(all(type(value) is dict for value in (version, info, image)) and type(containers) is list, "guard_api_shape")
  config = image.get("Config") or {}
  environment = config.get("Env")
  _require(type(environment) is list and all(type(v) is str and "=" in v for v in environment), "guard_environment")
  keys = sorted(value.split("=", 1)[0] for value in environment)
  amd64 = [row for row in (image.get("Manifests") or []) if type(row) is dict and row.get("ID") == compiler.PROVIDER_PLATFORM_MANIFEST]
  identity = {"engine_id": info.get("ID"), "server_version": version.get("Version"),
    "kernel": info.get("KernelVersion"), "driver": info.get("Driver"), "cgroup_driver": info.get("CgroupDriver"),
    "security_options": info.get("SecurityOptions"), "runtimes_sha256": _sha(component.canonical_json_v1(info.get("Runtimes"))),
    "provider_size": image.get("Size"), "rootfs_sha256": _sha(component.canonical_json_v1(image.get("RootFS"))),
    "env_keys_sha256": _sha(component.canonical_json_v1(keys)),
    "platform_manifest": amd64[0].get("ID") if len(amd64) == 1 else None,
    "unpacked_bytes": (((amd64[0].get("ImageData") or {}).get("Size") or {}).get("Unpacked"))
    if len(amd64) == 1 and amd64[0].get("Available") is True else None}
  _require(identity == EXPECTED and info.get("DockerRootDir") == "/var/lib/docker" and info.get("CgroupVersion") == "2" and
    image.get("Id") == compiler.PROVIDER_ID and image.get("RepoDigests") == [compiler.PROVIDER] and
    config.get("Volumes") in (None, {}) and len(set(keys)) == len(keys), "guard_identity_drift")
  try:
    _require(tuple(map(int, version["MinAPIVersion"].split("."))) <= (1, 55) <= tuple(map(int, version["ApiVersion"].split("."))), "guard_api_version")
  except (KeyError, TypeError, ValueError) as error:
    raise Gate2Refusal("guard_api_version") from error
  _require(len(containers) == len(expected_cids) and all(type(row) is dict and row.get("State") == "exited" for row in containers)
    and {row.get("Id") for row in containers} == set(expected_cids), "guard_container_set")
  return {"version": version, "info": info, "image": image, "containers": containers,
    "rpc": _rpc_json_facts_v1(client.facts), "identity": identity}


@contextmanager
def c6_export_fault_v1(output):
  output = Path(output)
  original = compiler._export_member_open
  seen = [False]
  class FirstWriteFault:
    def __init__(self, file):
      self.file = file
    def write(self, data):
      _require(not seen[0], "c6_multiple_writes")
      seen[0] = True
      raise OSError("labelled synthetic C6 first ELF write fault")
    def __getattr__(self, name):
      return getattr(self.file, name)
    def __enter__(self):
      return self
    def __exit__(self, *details):
      return self.file.__exit__(*details)
  def opener(path):
    file = original(path)
    return FirstWriteFault(file) if Path(path) == output / "engine.unaccepted" else file
  compiler._export_member_open = opener
  try:
    yield
  finally:
    compiler._export_member_open = original


def kernel_delta_v1(stage, before, after, compiler_stderr):
  if not all(type(raw) is bytes and len(raw) <= 192 * 1024 for raw in (before, after)) or not after.startswith(before):
    return {"passed": False, "delta_sha256": None, "direct_pid_cgroup_observation": False}
  delta = after[len(before):]
  if stage != "C3":
    return {"passed": not delta, "delta_sha256": _sha(delta), "direct_pid_cgroup_observation": False}
  try:
    lines = [re.sub(r"^\[\s*[0-9.]+\]\s*", "", line) for line in delta.decode("ascii").splitlines()]
    banners = [line for line in lines if re.fullmatch(r"(?:[^\s:]+/)?as(?:: as)?: potentially unexpected fatal signal 25\.", line)]
    cpu = [line for line in lines if re.fullmatch(r"CPU: [0-9]+ PID: [0-9]+ Comm: as +Not tainted 6\.6\.87\.2-microsoft-standard-WSL2 #1", line)]
    core = [line for line in lines if re.fullmatch(r"Process [0-9]+\(as\) has RLIMIT_CORE set to 1", line)]
    audit = [line for line in lines if re.fullmatch(r'audit: type=1701 audit\([0-9.:]+\): .*\buid=1000\b.*\bgid=1000\b.*\bcomm="as" .*\bsig=25\b.*', line)]
    def allowed(line):
      if line in banners + cpu + core or line == "Aborting core":
        return True
      if re.fullmatch(r"(?:RIP|RSP|RAX|RDX|RBP|R10|R13|FS): [0-9A-Fa-fx: ]+(?:[A-Z_0-9]+: [0-9A-Fa-fx: ]+)*", line):
        return True
      if re.fullmatch(r"Code: (?:[0-9a-fA-F<> ]+|Unable to access opcode bytes at 0x[0-9a-fA-F]+\.)", line):
        return True
      return line in audit
    host_pid = int(re.search(r"\bPID: ([0-9]+)\b", cpu[0])[1]) if len(cpu) == 1 else 0
    namespace_pid = int(re.search(r"^Process ([0-9]+)\(", core[0])[1]) if len(core) == 1 else 0
    audit_pids = re.findall(r"\bpid=([0-9]+)\b", audit[0]) if len(audit) == 1 else []
    # The immutable B2 original has host CPU PID1120 and namespace core
    # PID12 (and host1126/core18). A CPU/core equality check is wrong.
    # Audit pid, when present, is host-native and MUST match CPU PID.
    audit_bound = not audit or len(audit) == 1 and len(audit_pids) == 1 and int(audit_pids[0]) == host_pid
    passed = (len(banners) == len(cpu) == len(core) == 1 and lines.count("Aborting core") == 1 and
      host_pid > 0 and namespace_pid > 0 and audit_bound and
      b"File size limit exceeded" in compiler_stderr and all(allowed(line) for line in lines))
  except (UnicodeError, TypeError):
    passed = False
  return {"passed": passed, "delta_sha256": _sha(delta), "direct_pid_cgroup_observation": False}


def _measure_v1():
  c = os.statvfs("/mnt/c")
  ext4 = os.statvfs("/")
  return {"c_free_bytes": c.f_bavail * c.f_frsize,
    "ext4_used_bytes": (ext4.f_blocks - ext4.f_bfree) * ext4.f_frsize}


def _allocated_v1(root):
  total, count = 0, 0
  for directory, dirs, files in os.walk(root, followlinks=False):
    for name in dirs + files:
      count += 1
      _require(count <= 1024, "retained_entry_bound")
      row = os.lstat(Path(directory) / name)
      _require(not stat.S_ISLNK(row.st_mode), "retained_symlink")
      total += row.st_blocks * 512
  return total + os.lstat(root).st_blocks * 512


def _allocation_summary_v1(root):
  root = Path(root)
  payloads = {"engine.c", "engine.compiler-originals/compiler.stdout.original",
    "engine.compiler-originals/compiler.stderr.original", "engine.compiler-originals/engine.unaccepted"}
  paths = [root]
  for directory, dirs, files in os.walk(root, followlinks=False):
    for name in dirs + files:
      _require(len(paths) < 1024, "retained_entry_bound")
      paths.append(Path(directory) / name)
  data, control = 0, 0
  for path in paths:
    info = path.lstat()
    _require(not stat.S_ISLNK(info.st_mode), "retained_symlink")
    allocated = info.st_blocks * 512
    data += allocated
    if path == root or path.relative_to(root).as_posix() not in payloads:
      control += allocated
  return {"data_bytes": data, "control_data_bytes": control, "entries": len(paths),
    "metadata_upper_bytes": len(paths) * 4096}


def _crash_listing_v1(path, deadline):
  rows = []
  with os.scandir(CRASH_DIRECTORY) as entries:
    for index, entry in enumerate(entries):
      _require(index < 16384 and time.monotonic_ns() < deadline, "crash_listing_bound")
      if not entry.name.startswith("wsl-crash-"):
        continue
      info = entry.stat(follow_symlinks=False)
      _require(stat.S_ISREG(info.st_mode), "crash_listing_kind")
      rows.append([entry.name, info.st_size, info.st_mtime_ns])
      _require(len(rows) <= 128, "crash_listing_bound")
  return write_record_v1(path, sorted(rows), cap=16384, absolute_deadline_ns=deadline)


def _guard_snapshot_v1(output, deadline, *, gpu):
  output.mkdir(mode=0o700)
  result = {"boot_id": compiler._compiler_proc_read_v1("/proc/sys/kernel/random/boot_id", 64).decode("ascii").strip(),
    "measure": _measure_v1(), "crashes": _crash_listing_v1(output / "crashes.original.json", deadline)}
  for kind in ("dmesg", "journal", "gpu") if gpu else ("dmesg", "journal"):
    directory = output / kind
    directory.mkdir(mode=0o700)
    result[kind] = capture_guard_v1(kind, output_dir=directory, absolute_deadline_ns=deadline)
  if gpu:
    _require(_bound_descriptor(result["gpu"]["stdout"], cap=4096).strip() == b"", "gpu_busy")
  return result


def _http_json_v1(raw):
  _require(type(raw) is bytes and len(raw) <= 262144, "inspect_http_bound")
  head, separator, body = raw.partition(b"\r\n\r\n")
  _require(separator and len(head) <= 8192, "inspect_http_header")
  lines, fields = head.split(b"\r\n"), {}
  _require(re.fullmatch(rb"HTTP/1\.[01] 200 [\x20-\x7e]*", lines[0]) is not None, "inspect_http_status")
  for line in lines[1:]:
    name, colon, value = line.partition(b":")
    name = name.lower()
    _require(colon and name not in fields, "inspect_http_header")
    fields[name] = value.strip()
  _require(b"content-encoding" not in fields and not (b"content-length" in fields and b"transfer-encoding" in fields), "inspect_http_header")
  if fields.get(b"transfer-encoding") == b"chunked":
    decoded = bytearray()
    while True:
      length, separator, body = body.partition(b"\r\n")
      _require(separator and re.fullmatch(rb"[0-9A-Fa-f]{1,16}", length), "inspect_http_chunk")
      size = int(length, 16)
      if size == 0:
        _require(body == b"\r\n", "inspect_http_chunk")
        break
      _require(size <= 262144 - len(decoded) and len(body) >= size + 2 and body[size:size + 2] == b"\r\n", "inspect_http_chunk")
      decoded.extend(body[:size])
      body = body[size + 2:]
    body = bytes(decoded)
  else:
    length = fields.get(b"content-length", b"")
    _require(re.fullmatch(rb"[0-9]{1,10}", length) is not None and int(length) == len(body) and
      b"transfer-encoding" not in fields, "inspect_http_length")
  return _json(body, 262144, canonical=False)


def _post_inspect_v1(cid, output, deadline):
  output.mkdir(mode=0o700)
  client = compiler._DockerClientV1(output, deadline)
  client.RPC_LIMIT = 1
  actual = client.request("GET", "/containers/" + cid + "/json?size=1", deadline_ns=min(deadline, time.monotonic_ns() + 5_000_000_000))
  raw = _read(output / "RPC01.reply.original", 262144)
  _require(actual == _http_json_v1(raw), "inspect_original_binding")
  return {"value": actual, "request": _descriptor(output / "RPC01.request.original", _read(output / "RPC01.request.original", 8192)),
    "reply": _descriptor(output / "RPC01.reply.original", raw), "rpc": _rpc_json_facts_v1(client.facts)}


def _load_observations_v1(root, stage, original):
  output = root / "outputs" / stage
  owner = _json(_bound_descriptor(original["owner"], root=output, cap=RECORD_LIMIT))
  retained = output / "engine.compiler-originals"
  header = _bound_descriptor(original["header"], root=retained, cap=65536)
  actual = {name: _bound_descriptor(desc, root=retained, cap=16777216 if name == "elf" else 1048576)
    for name, desc in original["members"].items()}
  receipt = _json(_bound_descriptor(original["receipt"], root=retained, cap=8192))
  inspect = original["inspect"]
  reply = _bound_descriptor(inspect["reply"], root=output, cap=262144)
  request = _bound_descriptor(inspect["request"], root=output, cap=8192)
  _require(request.startswith(("GET /v1.55/containers/" + owner["cid"] + "/json?size=1 HTTP/1.1\r\n").encode("ascii")), "inspect_request_binding")
  final = _http_json_v1(reply)
  _require(final == inspect["value"], "inspect_value_drift")
  signals, wait_replies, rpc_raws = [], [], {}
  _require(type(owner.get("rpc")) is dict and type(owner["rpc"].get("attempts")) is int, "rpc_original_inventory")
  expected_files = {"RPC%02d.%s.original" % (number, role) for number in range(1, owner["rpc"]["attempts"] + 1)
    for role in ("request", "reply")}
  _require(set(original["owner_rpc_originals"]) == expected_files, "rpc_original_inventory")
  for name, desc in original["owner_rpc_originals"].items():
    raw = _bound_descriptor(desc, root=retained, cap=262144)
    rpc_raws[name] = raw
    if name.endswith("request.original") and b"/kill?" in raw.split(b"\r\n", 1)[0]:
      signals.append(raw.split(b"\r\n", 1)[0].decode("ascii"))
  for number in range(1, owner["rpc"]["attempts"] + 1):
    request = rpc_raws["RPC%02d.request.original" % number].split(b"\r\n", 1)[0]
    if request == ("POST /v1.55/containers/" + owner["cid"] + "/wait?condition=not-running HTTP/1.1").encode("ascii"):
      wait_replies.append(_http_json_v1(rpc_raws["RPC%02d.reply.original" % number]))
  before, after = original["before"], original["after"]
  kernel = kernel_delta_v1(stage, _bound_descriptor(before["dmesg"]["stdout"], root=output, cap=192 * 1024),
    _bound_descriptor(after["dmesg"]["stdout"], root=output, cap=192 * 1024), actual["stderr"])
  _require(kernel == original["kernel"] and kernel["passed"], "kernel_delta")
  _require(_bound_descriptor(before["crashes"], root=output, cap=16384) ==
    _bound_descriptor(after["crashes"], root=output, cap=16384), "crash_listing_drift")
  _require(before["boot_id"] == after["boot_id"] == original["boot_id"], "boot_drift")
  return owner, {"header_original": header, "members": actual, "final_inspect": final,
    "owner_call_elapsed_ns": original["owner_call_elapsed_ns"],
    "published_exists": os.path.lexists(output / "engine"), "boot_id": original["boot_id"],
    "mounts_sha256": MOUNTS_SHA256, "owner_receipt": receipt,
    "owner_signal_requests": signals, "wait_replies": wait_replies,
    "c3_sigxfsz_attributable": kernel["passed"]}


def _invocation_record_v1(stage, commit, packet_sha, result_sha, accounting_sha, previous_completion_sha):
  return {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_gate2_c_invocation_v1", "stage": stage,
    "code_commit": commit, "packet_sha256": packet_sha, "result_sha256": result_sha,
    "accounting_sha256": accounting_sha, "previous_completion_sha256": previous_completion_sha,
    "returned_successfully": True}


def complete_c_invocation_v1(stage, *, project_root, returned_result, expected_packet_sha256, expected_code_commit):
  """Trusted caller only, immediately after run_c_v1 actually returns."""
  _require(stage in STAGES and os.getuid() == os.getgid() == os.geteuid() == os.getegid() == 1000, "completion_actor_stage")
  _require(type(returned_result) is dict and compiler._json_bound(returned_result) <= 65536 and
    _sha_shape(expected_packet_sha256) and type(expected_code_commit) is str and
    re.fullmatch("[0-9a-f]{40}", expected_code_commit), "completion_input")
  root = Path(project_root)
  _require(root.is_absolute() and root.resolve(strict=True) == root and root.stat().st_dev == Path("/").stat().st_dev and
    os.statvfs(root).f_frsize == 4096, "completion_root_backing")
  output = root / "outputs" / stage
  persisted, measurements = None, []
  try:
    result_path = output / "run.result.original.json"
    result_raw = _read(result_path, 65536)
    result = _json(result_raw, 65536)
    _require(set(returned_result) == set(result) | {"accounting", "ledger_after", "final_measurement", "tail_growth_bytes"} and
      all(returned_result[key] == value for key, value in result.items()) and result.get("stage") == stage and
      result.get("passed") is True and result.get("accounting_pending") is True and
      result.get("packet_sha256") == expected_packet_sha256 and result.get("code_commit") == expected_code_commit,
      "completion_return_binding")
    deadline = result.get("completion_deadline_ns")
    _require(type(deadline) is int and time.monotonic_ns() < deadline, "completion_deadline")
    footer_path = output / "run.accounting.original.json"
    footer_raw = _bound_descriptor(returned_result["accounting"], root=output, cap=8192)
    _require(returned_result["accounting"]["path"] == str(footer_path), "completion_accounting_path")
    footer = _json(footer_raw, 8192)
    _require(footer.get("comparison_complete") is True and footer.get("stage") == stage and
      footer.get("packet_sha256") == expected_packet_sha256 and footer.get("result") == _descriptor(result_path, result_raw) and
      footer.get("previous_sha256") == result.get("previous_sha256") and
      footer.get("ledger_after") == returned_result["ledger_after"] and
      footer.get("tail_reserved_bytes") == RECORD_LIMIT, "completion_accounting_binding")
    def budget(*, prospective):
      _require(time.monotonic_ns() < deadline, "completion_deadline")
      measure = _measure_v1()
      measurements.append(measure)
      retained = _allocation_summary_v1(output)
      prefix = footer["retained_data_bytes"] + footer["retained_metadata_upper_bytes"]
      tail_retained = max(0, retained["data_bytes"] + retained["metadata_upper_bytes"] - prefix)
      tail_growth = interval_charge_v1(footer["interval_after_measurement"], measure, retained_bytes=tail_retained)
      future = (32768 if prospective else 0) + 32768
      _require(tail_growth + tail_retained + future <= RECORD_LIMIT, "completion_tail_bound")
      _require(2 * (retained["data_bytes"] + retained["metadata_upper_bytes"]) + future <= C_LIMIT and
        2 * (retained["control_data_bytes"] + retained["metadata_upper_bytes"]) + future <= CONTROL_LIMIT,
        "completion_retained_cap")
      reserve_v1(charged=footer["ledger_after"], liability=2097152, c_free_bytes=measure["c_free_bytes"])
      _require(time.monotonic_ns() < deadline, "completion_deadline")
    budget(prospective=True)
    record = _invocation_record_v1(stage, expected_code_commit, expected_packet_sha256,
      _sha(result_raw), _sha(footer_raw), result["previous_completion_sha256"])
    persisted = write_record_v1(output / "outer.invocation.original.json", record, cap=8192,
      absolute_deadline_ns=deadline, return_facts=True)
    budget(prospective=False)
    return dict(persisted, completion_deadline_ns=deadline, external_approval=False)
  except (Gate2Refusal, OSError, ValueError, TypeError, KeyError) as error:
    raise Gate2Refusal("c_completion_stopped", {"stage": stage, "cause": getattr(error, "cause", type(error).__name__),
      "failure_facts": getattr(error, "facts", {}), "returned_result": returned_result, "measurements": measurements,
      "write_facts": None if persisted is None else persisted["write_facts"],
      "descriptor": None if persisted is None else persisted["descriptor"], "external_approval": False}) from error


def _previous_v1(root, packet, packet_sha, count, completion_authorities):
  _require(type(packet.get("initial_charged_bytes")) is int, "packet_ledger")
  _require(type(completion_authorities) is dict and set(completion_authorities) == set(STAGES[:count]), "completion_authority_set")
  # These descriptors are external authority inputs, like expected_packet_sha256.
  _require(compiler._json_bound(completion_authorities) <= 65536, "completion_authority_bound")
  authorities = {stage: dict(desc) for stage, desc in completion_authorities.items() if type(desc) is dict}
  _require(len(authorities) == count, "completion_authority_descriptor")
  previous, charged, cids, rows = None, packet["initial_charged_bytes"], list(B_CIDS), []
  previous_completion = None
  for stage in STAGES[:count]:
    path = root / "outputs" / stage / "run.result.original.json"
    try:
      _require(not os.path.lexists(path.parent / "run.refusal.original.json"), "prior_stage_refused")
      raw = _read(path, 65536)
      row = _json(raw, 65536)
      _require(row["stage"] == stage and row["passed"] is True and row["packet_sha256"] == packet_sha and
        row["previous_sha256"] == previous and row["accounting_pending"] is True and
        row["ledger_before"] == charged and row.get("code_commit") == packet["code_review"]["commit"] and
        row.get("previous_completion_sha256") == previous_completion and
        type(row.get("completion_deadline_ns")) is int and row["completion_deadline_ns"] > COMPLETION_RESERVE_NS,
        "stage_chain")
      original = _json(_bound_descriptor(row["observations"], root=path.parent, cap=RECORD_LIMIT))
      source_path = path.parent / "engine.c"
      source = component.component_source_v1("c1" if stage == "C6" else stage.lower())
      _require(_read(source_path, component.SOURCE_LIMIT) == source and
        row.get("source_sha256") == original.get("source_sha256") == _sha(source), "prior_source_drift")
      seed_raw = _read(path.parent / "component.seed.original.json", 4096)
      _require(seed_raw == component.canonical_json_v1(packet["seed"]) and _sha(seed_raw) == packet["seed_sha256"], "prior_seed_drift")
      admission_raw = _read(path.parent / "component.admission.original.json", 4096)
      admission = _json(admission_raw, 4096)
      expires = admission.get("expires_unix_ns")
      _require(type(expires) is int and expires >= component.ADMISSION_LIFETIME_NS, "prior_admission_time")
      owner_root = _owner_project_root_v1(root, packet)
      expected_admission = component.component_admission_v1(project_root=owner_root, review=packet["code_review"],
        seed_sha256=packet["seed_sha256"], bindings=packet["seed"]["bindings"],
        source_relative=str(source_path.relative_to(owner_root)), source=source,
        executable_relative=str((path.parent / "engine").relative_to(owner_root)),
        physical_plan_sha256=packet["physical_plan"]["sha256"], boot_id=packet["boot_id"],
        now_unix_ns=expires - component.ADMISSION_LIFETIME_NS)
      _require(admission == expected_admission, "prior_admission_drift")
      owner, observations = _load_observations_v1(root, stage, original)
      evaluated = evaluate_c_v1(stage, owner, observations)
      _require(evaluated["passed"] and evaluated == _json(_bound_descriptor(row["evaluation"], root=path.parent, cap=8192)), "prior_comparison")
      footer_path = path.parent / "run.accounting.original.json"
      footer_raw = _read(footer_path, 8192)
      footer = _json(footer_raw, 8192)
      _require(footer.get("artifact_kind") == "vast_fixture_compiler_gate2_c_accounting_v1" and
        footer.get("comparison_complete") is True and footer.get("stage") == stage and
        footer.get("packet_sha256") == packet_sha and footer.get("previous_sha256") == previous and
        footer.get("result") == _descriptor(path, raw) and footer.get("ledger_before") == charged and
        footer.get("interval_before_measurement") == original["interval_before_measurement"] and
        footer.get("idle_gap_charged_bytes") == 0 and footer.get("tail_reserved_bytes") == RECORD_LIMIT,
        "stage_accounting_binding")
      completion_path = path.parent / "outer.invocation.original.json"
      _require(authorities[stage].get("path") == str(completion_path), "completion_authority_path")
      completion_raw = _bound_descriptor(authorities[stage], root=path.parent, cap=8192)
      completion = _json(completion_raw, 8192)
      _require(type(completion.get("schema_version")) is int and completion.get("returned_successfully") is True and
        completion == _invocation_record_v1(stage, packet["code_review"]["commit"], packet_sha,
        _sha(raw), _sha(footer_raw), previous_completion), "completion_authority_binding")
      actual = _allocation_summary_v1(path.parent)
      footer_allocated = footer_path.stat().st_blocks * 512
      completion_allocated = completion_path.stat().st_blocks * 512
      stage_directory_allocated = path.parent.stat().st_blocks * 512
      _require(2 * (footer_allocated + completion_allocated + stage_directory_allocated + 8192) + 32768 <= RECORD_LIMIT and
        2 * (actual["data_bytes"] + actual["metadata_upper_bytes"]) + 32768 <= C_LIMIT and
        2 * (actual["control_data_bytes"] + actual["metadata_upper_bytes"]) + 32768 <= CONTROL_LIMIT,
        "prior_completion_tail_bounds")
      prefix_upper = actual["data_bytes"] - footer_allocated - completion_allocated
      prefix_lower = max(0, prefix_upper - stage_directory_allocated)
      metadata = (actual["entries"] - 2) * 4096
      control_upper = actual["control_data_bytes"] - footer_allocated - completion_allocated
      control_lower = max(0, control_upper - stage_directory_allocated)
      _require(footer.get("retained_metadata_upper_bytes") == metadata and
        type(footer.get("retained_data_bytes")) is int and prefix_lower <= footer["retained_data_bytes"] <= prefix_upper and
        type(footer.get("control_data_bytes")) is int and control_lower <= footer["control_data_bytes"] <= control_upper,
        "prior_retained_accounting")
      size_rw = observations["final_inspect"].get("SizeRw")
      _require(type(size_rw) is int and 0 <= size_rw <= RUNTIME_STOP, "prior_size_rw")
      before, after = footer["interval_before_measurement"], footer["interval_after_measurement"]
      minimum_charge = interval_charge_v1(before, after, retained_bytes=prefix_lower + metadata,
        size_rw=size_rw) + prefix_lower + metadata + RECORD_LIMIT
      maximum_charge = interval_charge_v1(before, after, retained_bytes=prefix_upper + metadata,
        size_rw=size_rw) + prefix_upper + metadata + RECORD_LIMIT
      gross = interval_charge_v1(before, after, retained_bytes=0)
      nonoutput_lower, nonoutput_upper = max(0, gross - prefix_upper), max(0, gross - prefix_lower)
      _require(footer.get("future_copy_upper_bytes") == footer["retained_data_bytes"] + metadata and
        footer.get("retained_all_forms_upper_bytes") == 2 * (footer["retained_data_bytes"] + metadata) + RECORD_LIMIT <= C_LIMIT and
        footer.get("control_all_forms_upper_bytes") == 2 * (footer["control_data_bytes"] + metadata) + RECORD_LIMIT <= CONTROL_LIMIT,
        "prior_retained_bounds")
      _require(type(footer.get("nonoutput_growth_bytes")) is int and
        nonoutput_lower <= footer["nonoutput_growth_bytes"] <= min(RUNTIME_STOP, nonoutput_upper), "prior_nonoutput_growth")
      _require(type(footer["charge_bytes"]) is int and minimum_charge <= footer["charge_bytes"] <= maximum_charge and
        footer["ledger_after"] == charged + footer["charge_bytes"] <= SEAL_BYTES and owner["cid"] not in cids, "stage_ledger")
    except (OSError, KeyError, TypeError, ValueError) as error:
      raise Gate2Refusal("prior_stage_incomplete") from error
    previous, charged = _sha(footer_raw), footer["ledger_after"]
    previous_completion = _sha(completion_raw)
    cids.append(owner["cid"])
    rows.append((row, original, observations, footer))
  return previous, charged, cids, rows, previous_completion


def validated_c1_binding_v1(*, project_root, packet_descriptor, expected_packet_sha256, expected_code_commit, completion_authorities):
  root = Path(project_root)
  packet = validate_packet_v1(project_root=root, packet_descriptor=packet_descriptor,
    expected_packet_sha256=expected_packet_sha256, expected_code_commit=expected_code_commit, _stage="D")
  if packet.get("resume_context") is not None:
    boot = compiler._compiler_proc_read_v1("/proc/sys/kernel/random/boot_id", 64).decode("ascii").strip()
    _require(boot == packet["boot_id"], "resume_boot_drift")
  _, charged, cids, rows, _ = _previous_v1(root, packet, expected_packet_sha256, 6, completion_authorities)
  _require(len(cids) == len(set(cids)) == 9 and SEAL_BYTES - charged >= 2097152, "d_chain_reserve")
  first, original, observations, _ = rows[0]
  raw = observations["members"]["elf"]
  _require(_native_elf(raw) and original["source_sha256"] == component.SOURCE_SHA256["c1"], "d_c1_binding")
  return {"elf_path": str(root / "outputs/C1/engine.compiler-originals/engine.unaccepted"),
    "elf_size_bytes": len(raw), "elf_sha256": _sha(raw), "source_sha256": component.SOURCE_SHA256["c1"],
    "receipt_sha256": original["owner"]["sha256"], "all_cids": cids, "remaining_seal_bytes": SEAL_BYTES - charged,
    "last_after_measurement": rows[-1][3]["interval_after_measurement"], "last_tail_credit_bytes": 0}


def run_c_v1(stage, *, project_root, packet_descriptor, expected_packet_sha256, expected_code_commit, completion_authorities):
  _require(stage in STAGES and os.getuid() == os.getgid() == os.geteuid() == os.getegid() == 1000, "c_actor_stage")
  root = Path(project_root)
  _require(root.is_absolute() and root.resolve(strict=True) == root and root.is_dir() and
    root.stat().st_dev == Path("/").stat().st_dev and os.statvfs(root).f_frsize == 4096, "c_root_backing")
  started = time.monotonic_ns()
  completion_deadline = started + RUN_NS
  deadline = completion_deadline - COMPLETION_RESERVE_NS
  interval_before = _measure_v1()
  packet = validate_packet_v1(project_root=root, packet_descriptor=packet_descriptor,
    expected_packet_sha256=expected_packet_sha256, expected_code_commit=expected_code_commit, _stage=stage)
  number = STAGES.index(stage)
  previous, charged, cids, prior_rows, previous_completion = _previous_v1(root, packet, expected_packet_sha256, number, completion_authorities)
  _require(all(not os.path.lexists(root / "outputs" / later) for later in STAGES[number:]), "c_stage_already_attempted")
  reserve_v1(charged=charged, liability=C_LIMIT + 4194304 + 2097152,
    c_free_bytes=interval_before["c_free_bytes"])
  _require(time.monotonic_ns() < deadline, "c_absolute_deadline")
  outputs = root / "outputs"
  if not outputs.exists():
    outputs.mkdir(mode=0o700)
  _require(outputs.resolve(strict=True) == outputs and outputs.is_dir(), "c_outputs")
  output = outputs / stage
  output.mkdir(mode=0o700)
  controls = output / "controls"
  controls.mkdir(mode=0o700)
  owner = None
  try:
    before = _guard_snapshot_v1(controls / "before", min(started + 5_000_000_000, deadline), gpu=True)
    _require(before["boot_id"] == packet["boot_id"], "c_boot_drift")
    if prior_rows:
      prior_dmesg = prior_rows[-1][1]["after"]["dmesg"]["stdout"]
      _require(_bound_descriptor(prior_dmesg, cap=192 * 1024) ==
        _bound_descriptor(before["dmesg"]["stdout"], cap=192 * 1024), "interstage_kernel_drift")
    reserve_v1(charged=charged, liability=C_LIMIT + 4194304 + 2097152,
      c_free_bytes=before["measure"]["c_free_bytes"])
    identity_dir = controls / "identity"
    identity_dir.mkdir(mode=0o700)
    identity = observe_identity_v1(output_dir=identity_dir, expected_cids=cids,
      absolute_deadline_ns=min(started + 10_000_000_000, deadline))
    write_record_v1(controls / "identity.original.json", identity, cap=RECORD_LIMIT, absolute_deadline_ns=deadline)
    source = component.component_source_v1("c1" if stage == "C6" else stage.lower())
    source_path = output / "engine.c"
    _require(time.monotonic_ns() < deadline, "c_absolute_deadline")
    with source_path.open("xb") as file:
      _require(time.monotonic_ns() < deadline, "c_absolute_deadline")
      _require(file.write(source) == len(source), "source_short_write")
      _require(time.monotonic_ns() < deadline, "c_absolute_deadline")
      file.flush()
      _require(time.monotonic_ns() < deadline, "c_absolute_deadline")
      os.fsync(file.fileno())
    _require(time.monotonic_ns() < deadline, "c_absolute_deadline")
    seed_desc = write_record_v1(output / "component.seed.original.json", packet["seed"],
      cap=4096, absolute_deadline_ns=deadline)
    _require(seed_desc["sha256"] == packet["seed_sha256"], "seed_drift")
    owner_root = _owner_project_root_v1(root, packet)
    admission = component.component_admission_v1(project_root=owner_root, review=packet["code_review"],
      seed_sha256=seed_desc["sha256"], bindings=packet["seed"]["bindings"],
      source_relative=str(source_path.relative_to(owner_root)), source=source,
      executable_relative=str((output / "engine").relative_to(owner_root)),
      physical_plan_sha256=packet["physical_plan"]["sha256"], boot_id=packet["boot_id"])
    admission_desc = write_record_v1(output / "component.admission.original.json", admission,
      cap=4096, absolute_deadline_ns=deadline)
    retained = output / "engine.compiler-originals"
    owner_entry_ns = time.monotonic_ns()
    try:
      with c6_export_fault_v1(retained) if stage == "C6" else nullcontext():
        owner = compiler._compile_fixture_component_v1(project_root=owner_root, source_path=source_path,
          executable_path=output / "engine", admission=admission_desc,
          qualification=seed_desc, absolute_deadline_ns=deadline)
    except compiler.FixtureCompilerError as error:
      _require(hasattr(error, "facts") and type(error.facts) is dict, "owner_facts_missing")
      owner = error.facts
      _require(owner.get("causes") == error.causes, "owner_exception_binding")
    owner_elapsed_ns = time.monotonic_ns() - owner_entry_ns
    owner = dict(owner)
    owner["rpc"] = _rpc_json_facts_v1(owner.get("rpc"))
    owner_desc = write_record_v1(output / "outer.owner.original.json", owner, cap=RECORD_LIMIT, absolute_deadline_ns=deadline)
    _require(type(owner.get("cid")) is str and re.fullmatch("[0-9a-f]{64}", owner["cid"]), "c_actual_cid")
    actual_inspect = _post_inspect_v1(owner["cid"], controls / "final-inspect", deadline)
    after = _guard_snapshot_v1(controls / "after", deadline, gpu=False)
    _require(after["boot_id"] == packet["boot_id"], "c_boot_drift")
    raw_header = _read(retained / "export.header.original", 65536)
    member_names = {"stdout": "compiler.stdout.original", "stderr": "compiler.stderr.original", "elf": "engine.unaccepted"}
    members = {name: _descriptor(retained / filename, _read(retained / filename,
      16777216 if name == "elf" else 1048576)) for name, filename in member_names.items()}
    originals = {}
    for path in sorted(retained.glob("RPC*.original")):
      _require(len(originals) < 46, "owner_rpc_inventory")
      originals[path.name] = _descriptor(path, _read(path, 262144))
    _require(len(originals) == 2 * owner["rpc"]["attempts"], "owner_rpc_inventory")
    kernel = kernel_delta_v1(stage, _bound_descriptor(before["dmesg"]["stdout"], cap=192 * 1024),
      _bound_descriptor(after["dmesg"]["stdout"], cap=192 * 1024),
      _bound_descriptor(members["stderr"], cap=1048576))
    original = {"stage": stage, "owner": owner_desc, "boot_id": packet["boot_id"],
      "interval_before_measurement": interval_before,
      "owner_call_elapsed_ns": owner_elapsed_ns,
      "header": _descriptor(retained / "export.header.original", raw_header), "members": members,
      "receipt": _descriptor(retained / "owner.result.original.json", _read(retained / "owner.result.original.json", 8192)),
      "inspect": actual_inspect, "owner_rpc_originals": originals, "before": before, "after": after,
      "kernel": kernel, "source_sha256": _sha(source), "packet_sha256": expected_packet_sha256,
      "c6_synthetic_only": stage == "C6", "whole_chain_authority": False}
    observations_desc = write_record_v1(output / "observations.original.json", original, cap=RECORD_LIMIT, absolute_deadline_ns=deadline)
    reloaded_owner, observations = _load_observations_v1(root, stage, original)
    comparison = evaluate_c_v1(stage, reloaded_owner, observations)
    evaluation_desc = write_record_v1(output / "evaluation.original.json", comparison, cap=8192, absolute_deadline_ns=deadline)
    validate_packet_v1(project_root=root, packet_descriptor=packet_descriptor,
      expected_packet_sha256=expected_packet_sha256, expected_code_commit=expected_code_commit, _stage=stage)
    _require(_read(source_path, component.SOURCE_LIMIT) == source, "c_source_post_drift")
    result = {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_gate2_c_result_v1", "stage": stage,
      "passed": comparison["passed"], "packet_sha256": expected_packet_sha256, "previous_sha256": previous,
      "observations": observations_desc, "evaluation": evaluation_desc, "ledger_before": charged,
      "code_commit": expected_code_commit, "previous_completion_sha256": previous_completion,
      "completion_deadline_ns": completion_deadline,
      "accounting_pending": True, "source_sha256": _sha(source), "cid": owner["cid"],
      "c6_synthetic_only": stage == "C6", "whole_chain_authority": False}
    result_desc = write_record_v1(output / "run.result.original.json", result, cap=65536, absolute_deadline_ns=deadline)
    interval_after = _measure_v1()
    retained = _allocation_summary_v1(output)
    data, metadata, control = retained["data_bytes"], retained["metadata_upper_bytes"], retained["control_data_bytes"]
    retained_all_forms = 2 * (data + metadata) + RECORD_LIMIT
    control_all_forms = 2 * (control + metadata) + RECORD_LIMIT
    _require(retained_all_forms <= C_LIMIT and control_all_forms <= CONTROL_LIMIT, "c_retained_cap")
    size_rw = actual_inspect["value"].get("SizeRw")
    _require(type(size_rw) is int and 0 <= size_rw <= RUNTIME_STOP, "c_size_rw")
    gross = interval_charge_v1(interval_before, interval_after, retained_bytes=0)
    nonoutput = max(0, gross - data)
    _require(nonoutput <= RUNTIME_STOP, "c_runtime_growth")
    charge = interval_charge_v1(interval_before, interval_after, retained_bytes=data + metadata,
      size_rw=size_rw) + data + metadata + RECORD_LIMIT
    reserve_v1(charged=charged, liability=charge + 2097152, c_free_bytes=interval_after["c_free_bytes"])
    footer = {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_gate2_c_accounting_v1",
      "comparison_complete": comparison["passed"], "stage": stage, "packet_sha256": expected_packet_sha256,
      "previous_sha256": previous, "result": result_desc, "ledger_before": charged,
      "interval_before_measurement": interval_before, "interval_after_measurement": interval_after,
      "idle_gap_charged_bytes": 0, "tail_reserved_bytes": RECORD_LIMIT,
      "retained_data_bytes": data, "retained_metadata_upper_bytes": metadata,
      "control_data_bytes": control, "future_copy_upper_bytes": data + metadata,
      "retained_all_forms_upper_bytes": retained_all_forms, "control_all_forms_upper_bytes": control_all_forms,
      "nonoutput_growth_bytes": nonoutput, "charge_bytes": charge, "ledger_after": charged + charge}
    footer_desc = write_record_v1(output / "run.accounting.original.json", footer, cap=8192, absolute_deadline_ns=deadline)
    final_measure = _measure_v1()
    tail_growth = interval_charge_v1(interval_after, final_measure, retained_bytes=0)
    _require(tail_growth + 65536 <= RECORD_LIMIT, "c_final_tail_bound")
    reserve_v1(charged=charged, liability=charge + 2097152, c_free_bytes=final_measure["c_free_bytes"])
    _require(time.monotonic_ns() < deadline, "c_absolute_deadline")
    if not comparison["passed"]:
      raise Gate2Refusal("c_comparison_deviation", result)
    return dict(result, accounting=footer_desc, ledger_after=footer["ledger_after"],
      final_measurement=final_measure, tail_growth_bytes=tail_growth)
  except (Gate2Refusal, OSError, ValueError, TypeError, KeyError, compiler.FixtureCompilerError) as error:
    refusal = {"stage": stage, "cause": error.cause if isinstance(error, Gate2Refusal) else type(error).__name__,
      "owner_observed": owner is not None, "whole_chain_authority": False,
      "preserve_originals": True, "retry_authorized": False}
    budget_denied = refusal["cause"] in {"ledger_unknown", "ledger_reserve", "capacity_floor", "c_retained_cap",
      "c_runtime_growth", "c_final_tail_bound", "retained_entry_bound", "retained_symlink"}
    if not budget_denied and not os.path.lexists(output / "run.refusal.original.json") and time.monotonic_ns() < deadline:
      try:
        failed_measure = _measure_v1()
        failed_retained = _allocation_summary_v1(output)
        retained_upper = failed_retained["data_bytes"] + failed_retained["metadata_upper_bytes"]
        control_upper = failed_retained["control_data_bytes"] + failed_retained["metadata_upper_bytes"]
        _require(2 * retained_upper + RECORD_LIMIT <= C_LIMIT and
          2 * control_upper + RECORD_LIMIT <= CONTROL_LIMIT, "c_refusal_retained_cap")
        failed_charge = interval_charge_v1(interval_before, failed_measure,
          retained_bytes=retained_upper, size_rw=RUNTIME_STOP) + retained_upper + RECORD_LIMIT
        reserve_v1(charged=charged, liability=failed_charge + 2097152,
          c_free_bytes=failed_measure["c_free_bytes"])
        _require(time.monotonic_ns() < deadline, "c_absolute_deadline")
        write_record_v1(output / "run.refusal.original.json", refusal, cap=4096, absolute_deadline_ns=deadline)
      except (Gate2Refusal, OSError, ValueError) as write_error:
        refusal["refusal_write_failure"] = getattr(write_error, "facts", {})
    refusal["failure_facts"] = getattr(error, "facts", {})
    refusal["owner_facts"] = owner
    raise Gate2Refusal("c_stage_stopped", refusal) from error


def _native_elf(raw):
  return (len(raw) >= 64 and raw[:7] == b"\x7fELF\x02\x01\x01" and
    int.from_bytes(raw[16:18], "little") in (2, 3) and int.from_bytes(raw[18:20], "little") == 62
    and int.from_bytes(raw[20:24], "little") == 1)


def evaluate_c_v1(stage, owner, observations):
  """Pure comparison of actual originals; expected refusal never grants an ELF."""
  errors = []
  def check(ok, cause):
    if not ok and cause not in errors:
      errors.append(cause)
  try:
    _require(stage in STAGES and type(owner) is dict and type(observations) is dict, "comparison_input")
    success = stage == "C1"
    expected_causes = [] if success else ["export_OSError", "attach_incomplete"] if stage == "C6" else ["owner_wait_status"]
    check(owner.get("causes") == expected_causes, "owner_causes")
    for key, expected in (("accepted", False), ("forced", False), ("normal_closed", success),
      ("receipt_persisted", True), ("creation_unknown", False),
      ("start_unknown", False), ("start_attempted", True), ("signal_handlers_restored", True)):
      check(owner.get(key) is expected, "owner_" + key)
    check(owner.get("promotion") is None and observations.get("published_exists") is False, "published_executable")
    cid = owner.get("cid")
    check(type(cid) is str and re.fullmatch("[0-9a-f]{64}", cid) is not None, "cid")
    final = observations.get("final_inspect") or {}
    state = final.get("State") or {}
    check(final.get("Id") == cid and type(final.get("RestartCount")) is int and final["RestartCount"] == 0, "final_identity")
    for name in ("Running", "Restarting", "Paused", "Dead", "OOMKilled"):
      check(state.get(name) is False, "final_" + name)
    check(type(state.get("Pid")) is int and state["Pid"] == 0 and state.get("Error") == "", "final_process")
    exitcode = 0 if stage in ("C1", "C6") else 1
    check(type(state.get("ExitCode")) is int and state["ExitCode"] == exitcode, "container_status")
    waited = observations.get("wait_replies")
    check(type(waited) is list and len(waited) == 1 and type(waited[0]) is dict and
      type(waited[0].get("StatusCode")) is int and waited[0]["StatusCode"] == exitcode and
      waited[0].get("Error") in (None, {}), "wait_reply_status_error")
    closure = owner.get("closed" if success else "containment_native") or {}
    check(closure.get("closed") is True and type(closure.get("populated")) is int and
      closure["populated"] == 0 and closure.get("procs") == [] and closure.get("init_absent") is True, "native_closure")
    live = owner.get("live") or {}
    check(live.get("boot_id") == observations.get("boot_id") and
      live.get("mounts_sha256") == observations.get("mounts_sha256"), "native_binding")
    check(observations.get("owner_signal_requests") == [], "owner_signals")
    rpc = owner.get("rpc") or {}
    check(rpc.get("causes", []) == [] and rpc.get("controlled_socket") is False and rpc.get("controlled_clock") is False and
      type(rpc.get("attempts")) is int and
      1 <= rpc["attempts"] <= 23 and type(rpc.get("metadata_bytes")) is int and
      0 <= rpc["metadata_bytes"] <= 262144 and type(rpc.get("rpc")) is list and
      len(rpc["rpc"]) == rpc.get("attempts"), "owner_rpc")
    for row in rpc.get("rpc", []):
      check(row.get("causes") == [] and row.get("complete") is True and
        all(row.get(key) is True for key in ("request_persisted", "reply_persisted", "request_send_complete",
        "request_close_completed", "reply_close_completed", "socket_closed")) and
        all(row.get(key) is False for key in ("request_write_extent_unknown", "reply_write_extent_unknown")), "rpc_persistence")
      peer = row.get("peer")
      check(type(peer) is dict and set(peer) == {"pid", "uid", "gid"} and
        type(peer.get("pid")) is int and peer["pid"] > 0 and type(peer.get("uid")) is int and peer["uid"] == 0 and
        type(peer.get("gid")) is int and peer["gid"] >= 0 and
        row.get("epoch_before") and row.get("epoch_before") == row.get("epoch_after"), "rpc_peer_epoch")
      check(row.get("status") == 101 if row.get("upgraded") is True else
        type(row.get("status")) is int and 200 <= row["status"] < 300 and row.get("reply_eof") is True, "rpc_status_eof")
    captured = owner.get("failed_operation" if stage == "C6" else "export") or {}
    framed = observations.get("header_original")
    _require(type(framed) is bytes and 12 < len(framed) <= 65536 and framed[:8] == b"VASTCE1\n" and
      struct.unpack("!I", framed[8:12])[0] == len(framed) - 12, "header_frame")
    header = _json(framed[12:], 65524)
    check(header == captured.get("header") and header.get("schema_version") == 1 and
      type(header.get("schema_version")) is int and header.get("artifact_kind") == "vast_fixture_compiler_export_v1", "header_binding")
    source = component.component_source_v1("c1" if stage == "C6" else stage.lower())
    check(header.get("source") == {"size_bytes": len(source), "sha256": _sha(source)}, "source_binding")
    runtime, child = header.get("runtime") or {}, header.get("compiler") or {}
    check(type(runtime.get("pid")) is int and runtime["pid"] == 1 and
      runtime.get("core") == [1, 1] and all(type(v) is int for v in runtime["core"]) and
      runtime.get("fsize") == [16777216, 16777216] and all(type(v) is int for v in runtime["fsize"]) and
      runtime.get("interpreter_elf64_amd64") is True and runtime.get("compiler_elf64_amd64") is True, "runtime_limits_abi")
    code = 0 if stage in ("C1", "C6") else 1 if stage in ("C2", "C3") else -15
    check(type(child.get("returncode")) is int and child["returncode"] == code and
      child.get("started") is True and child.get("reaped") is True and header.get("descendants_reaped") is True, "compiler_status_reap")
    expected = [[]] if stage in ("C1", "C6") else [["compiler_exit_nonzero"]]
    if stage in ("C4", "C5"):
      trigger = "stderr_overflow" if stage == "C4" else "compiler_deadline"
      expected = [[trigger, "compiler_term_attempted", "compiler_exit_nonzero"],
        [trigger, "compiler_term_attempted", "descendant_exit_nonzero", "compiler_exit_nonzero"]]
    check(header.get("causes") in expected, "publisher_causes")
    check(captured.get("header_close_completed") is True, "header_close")
    members = captured.get("members") or {}
    check(set(members) == {"stdout", "stderr", "elf"}, "export_member_set")
    actual = observations.get("members") or {}
    for name in ("stdout", "stderr", "elf"):
      row = members.get(name) or {}
      raw = actual.get(name)
      _require(type(raw) is bytes and len(raw) <= (16777216 if name == "elf" else 1048576), "member_bound")
      if stage == "C6" and name == "elf":
        check(row.get("size_bytes") is None and row.get("sha256") is None and
          row.get("persisted") is False and row.get("complete") is False and
          row.get("close_completed") is True and type(row.get("observed_bytes")) is int and
          0 < row["observed_bytes"] <= 65536, "c6_unknown_extent")
        continue
      desc = header.get("elf") if name == "elf" else child.get(name)
      check(type(desc) is dict and type(desc.get("size_bytes")) is int and desc["size_bytes"] == len(raw) and desc.get("sha256") == _sha(raw), "member_header_" + name)
      check(type(row.get("size_bytes")) is int and row["size_bytes"] == len(raw) and row.get("sha256") == _sha(raw) and
        type(row.get("observed_bytes")) is int and row["observed_bytes"] == len(raw) and row.get("observed_sha256") == _sha(raw) and
        all(row.get(key) is True for key in ("complete", "persisted", "close_completed")), "member_capture_" + name)
    for name in ("stdout", "stderr"):
      row = child.get(name) or {}
      check(row.get("eof") is True and type(row.get("observed_bytes")) is int and
        type(row.get("size_bytes")) is int and type(row.get("discarded_bytes")) is int and
        row["observed_bytes"] == row.get("size_bytes", -1) + row["discarded_bytes"], "channel_" + name)
      check(row.get("discarded_bytes", -1) > 0 and row.get("size_bytes") == 1048576 if stage == "C4" and name == "stderr"
        else row.get("discarded_bytes") == 0, "channel_discard_" + name)
      if stage in ("C1", "C5", "C6") or stage == "C4" and name == "stdout":
        check(row.get("size_bytes") == 0 and row.get("observed_bytes") == 0, "channel_empty_" + name)
    elf = header.get("elf") or {}
    if stage in ("C1", "C6"):
      check(elf.get("available") is True and type(elf.get("size_bytes")) is int and
        64 <= elf["size_bytes"] <= 16777216 and _sha_shape(elf.get("sha256")), "elf_available")
      if success:
        check(_native_elf(actual["elf"]), "elf_abi")
    else:
      check(elf == {"available": False, "size_bytes": 0, "sha256": _sha(b"")}, "negative_elf")
    receipt = observations.get("owner_receipt") or {}
    check(receipt.get("export_binding") is None if stage == "C6" else receipt.get("export_binding") == {
      "header_sha256": _sha(framed[12:]), "members": members, "complete": True}, "receipt_export_binding")
    check(captured.get("complete") is False and captured.get("client_stdout_eof") is False and
      owner.get("containment_close_wait") is True if stage == "C6" else
      captured.get("complete") is True and captured.get("client_stdout_eof") is True, "capture_completion")
    if stage == "C3":
      check(observations.get("c3_sigxfsz_attributable") is True, "c3_sigxfsz")
    if stage == "C5":
      check(type(observations.get("owner_call_elapsed_ns")) is int and
        45_000_000_000 <= observations["owner_call_elapsed_ns"] < RUN_NS, "c5_elapsed_minimum")
  except (Gate2Refusal, KeyError, TypeError, ValueError, AttributeError, OverflowError) as error:
    check(False, error.cause if isinstance(error, Gate2Refusal) else "comparison_malformed")
  return {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_gate2_c_comparison_v1",
    "stage": stage, "passed": not errors, "causes": errors, "whole_chain_authority": False}


if __name__ == "__main__":
  raise SystemExit(native_main_v1())
