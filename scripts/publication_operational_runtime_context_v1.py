"""Explicit, separately custodied bounded capture on the existing v3 spine."""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path

from publication_operational_request_domain_v1 import (
    NATIVE_OPERATIONAL_JSONL, canonical_json_v1, strict_json_object_v1,
    validate_native_header_v1,
)

CAPTURE_ROLE = "operational_request_context"
CAPTURE_KEY = "operational_capture"
CONTAINER_OPERATIONAL_ROOT = "/opt/vast/operational"
MODES = {"complete_qualification_operational_identity_v1",
         "bounded_native_diagnostic_operational_v1"}
CONTEXT_FIELDS = {"schema_version", "artifact_kind", "mode", "native_header",
                  "admission_limits", "sha256"}
OUTPUT_PATH_RULE = "request_output_dir_sibling_v1"


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _add_note(error, note):
    """Attach a note; Python 3.10 runtime images lack ``BaseException.add_note``."""
    note_adder = getattr(error, "add_note", None)
    if callable(note_adder):
        note_adder(note)
    else:
        error.__notes__ = [*getattr(error, "__notes__", ()), note]


def operational_output_dir_v1(request, raw):
    """Resolve a frozen path rule without changing original input/grant JSON."""
    capture = raw[CAPTURE_KEY]
    output_dir = Path(request.output_dir).absolute()
    expected = output_dir.parent / (output_dir.name + ".operational")
    declared = capture["output_dir"]
    if declared == OUTPUT_PATH_RULE:
        return expected
    _require(type(declared) is str and str(Path(declared)) == str(expected),
             "operational output is not the original request's exact sibling")
    return expected


def runtime_file_roles_v1(request, raw, legacy_roles):
    capture = raw.get(CAPTURE_KEY)
    if capture is None:
        _require(CAPTURE_KEY not in raw, "explicit capture must not be null")
        return frozenset(legacy_roles)
    _require(type(capture) is dict and set(capture) == {"mode", "output_dir"} and
             capture["mode"] in MODES, "unsupported operational runtime capture")
    declared = operational_output_dir_v1(request, raw)
    _require(declared.is_absolute() and not declared.is_symlink() and
             not os.path.lexists(declared), "operational output custody is invalid or already exists")
    return frozenset(legacy_roles) | {CAPTURE_ROLE}


def prepare_operational_child_dir_v1(raw, runtime_output):
    if CAPTURE_KEY not in raw:
        return None
    path = Path(runtime_output).parent / "operational"
    _require(not os.path.lexists(path), "operational child staging already exists")
    path.mkdir(mode=0o700)
    return path


def operational_mount_arguments_v1(raw, runtime_output, mount):
    if CAPTURE_KEY not in raw:
        return ()
    path = Path(runtime_output).parent / "operational"
    _require(path.is_dir() and not path.is_symlink(), "operational child staging is unsafe")
    return tuple(mount(str(path), CONTAINER_OPERATIONAL_ROOT, readonly=False))


def operational_launch_arguments_v1(raw, roles):
    if CAPTURE_KEY not in raw:
        return ()
    return ("--operational-request-context", str(roles[CAPTURE_ROLE].container_path),
            "--operational-output-dir", CONTAINER_OPERATIONAL_ROOT)


def copy_operational_child_v1(raw, runtime_output, request):
    if CAPTURE_KEY not in raw:
        return
    source_dir = Path(runtime_output).parent / "operational"
    target_dir = operational_output_dir_v1(request, raw)
    _materialize_operational_file_v1(request.project_root, source_dir, target_dir)


def _materialize_operational_file_v1(project_root, source_dir, target_dir, *, record_original_transfer=True):
    """Use the existing held-parent publication boundary for success or failure."""
    from publication_child_evidence_materializer_v1 import materialize_publication_child_evidence_group_v1
    from publication_physical_io_v1 import PhysicalRootCustodyV1
    _require(not os.path.lexists(target_dir), "operational destination already exists")
    with PhysicalRootCustodyV1.open(project_root, label="operational project custody") as custody:
        custody.ensure_directory_owned(target_dir, label="separate native operational output")
    result = materialize_publication_child_evidence_group_v1(
        project_root=project_root, source_dir=source_dir, output_dir=target_dir,
        target_names=(NATIVE_OPERATIONAL_JSONL,),
        evidence_mapping={NATIVE_OPERATIONAL_JSONL: NATIVE_OPERATIONAL_JSONL},
        allowed_preexisting_names=(),
        maximum_bytes=64 * 1024 * 1024, label="separate native operational evidence",
    )
    if record_original_transfer:
        from publication_operational_process_custody_v1 import record_original_native_transfer_v1
        record_original_native_transfer_v1(source_dir, target_dir, result)
    return result


@contextmanager
def operational_runtime_scratch_v1(raw, *, prefix, dir, request=None):
    """Preserve failed capture bytes before removing owned input staging."""
    if CAPTURE_KEY not in raw:
        with tempfile.TemporaryDirectory(prefix=prefix, dir=dir) as name:
            yield name
        return
    root = Path(dir).absolute()
    name = Path(tempfile.mkdtemp(prefix=prefix, dir=root))

    def cleanup():
        _require(name.parent == root and name.name.startswith(prefix) and
                 not name.is_symlink(), "operational scratch cleanup target drifted")
        shutil.rmtree(name)

    try:
        yield str(name)
    except BaseException as error:
        try:
            source = name / "operational"
            if source.is_dir() and any(source.iterdir()):
                if request is None:
                    _require(raw[CAPTURE_KEY]["output_dir"] != OUTPUT_PATH_RULE,
                             "original request is required to resolve failed output custody")
                    resolved = Path(raw[CAPTURE_KEY]["output_dir"])
                else:
                    resolved = operational_output_dir_v1(request, raw)
                target = Path(str(resolved) + ".failed")
                _require(source.parent == name and not source.is_symlink() and
                         target.is_absolute() and not os.path.lexists(target) and
                         target.parent.is_dir() and not target.parent.is_symlink(),
                         "failed operational custody destination is unsafe")
                leaves = tuple(source.iterdir())
                _require(len(leaves) == 1 and leaves[0].name == NATIVE_OPERATIONAL_JSONL,
                         "failed operational group contains unexpected paths")
                info = leaves[0].lstat()
                _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                         0 <= info.st_size <= 64 * 1024 * 1024,
                         "failed operational group exceeds its physical bound")
                # Do not rename through path-based parents after a failure.
                # A held original project root verifies every ancestor and
                # commits the retained bytes before owned staging is removed.
                project_root = root if request is None else request.project_root
                _materialize_operational_file_v1(project_root, source, target, record_original_transfer=False)
                _add_note(error, f"Original failed operational evidence retained at {target}")
            cleanup()
        except BaseException as custody_error:
            # Keep the original private stage if its evidence cannot be moved;
            # never mask the original process failure with a cleanup failure.
            _add_note(error, f"Failed evidence custody requires inspection at {name}: {custody_error}")
        raise
    else:
        cleanup()


def load_native_operational_context_v1(path, output_dir, *, run_id, system,
        scenario, codec, policy, deadline_ms, study_runtime_plan=None):
    if path is None and output_dir is None:
        return None, None
    _require(path is not None and output_dir is not None,
             "operational context and separate output must be declared together")
    path, output_dir = Path(path), Path(output_dir)
    _require(path.is_absolute() and output_dir.is_absolute() and
             not path.is_symlink() and not output_dir.is_symlink(), "operational context path is unsafe")
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
             0 < before.st_size <= 65_536, "operational context file exceeds its bound")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                 (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns),
                 "operational context open identity drift")
        with os.fdopen(os.dup(fd), "rb") as stream:
            raw = stream.read(65_537)
        value = strict_json_object_v1(raw, max_bytes=65_536)
        _require(canonical_json_v1(value) + b"\n" == raw and
                 set(value) == CONTEXT_FIELDS and value["schema_version"] == 1 and
                 value["artifact_kind"] == ("vast_finite_study_native_capture_context_v1" if study_runtime_plan is not None
                    else "vast_native_operational_capture_context_v1") and
                 value["mode"] in ({"finite-component-study"} if study_runtime_plan is not None else MODES), "operational capture context schema drifted")
        unsigned = {key: item for key, item in value.items() if key != "sha256"}
        _require(value["sha256"] == hashlib.sha256(canonical_json_v1(unsigned)).hexdigest(),
                 "operational capture context semantic seal drifted")
        after = os.fstat(fd)
        named = path.lstat()
        snapshot = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_nlink,
                                 item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        _require(snapshot(before) == snapshot(after) == snapshot(named),
                 "operational context changed while reading")
    finally:
        os.close(fd)
    header = value["native_header"]
    study_scope = None
    if study_runtime_plan is not None:
        from checkpoint_runtime_plan import validate_finite_study_runtime_plan_v1
        from canonical_systems_study_plan_v1 import stream_schedule
        validate_finite_study_runtime_plan_v1(study_runtime_plan)
        plan = study_runtime_plan["study_plan"]
        study_scope = {"kind": "finite-component-study", "plan_sha256": plan["sha256"],
            "max_frame_id": 441, "max_requests_per_arm": 10608, "max_operations": 32}
    validate_native_header_v1(header, study_scope=study_scope)
    for key, actual in {"run_id": run_id, "system": system, "scenario": scenario,
                        "codec": codec, "policy": policy, "deadline_ms": deadline_ms}.items():
        _require(header[key] == actual, f"operational original {key} binding drifted")
    _require(type(run_id) is str and run_id.isascii() and len(run_id) <= 64 and
             deadline_ms == 100.0, "operational request is outside the proved constructor domain")
    max_count = 241 if system in {"gstreamer_custom", "openvino_gva"} else 281
    min_step = 999_999_600
    if study_scope is not None:
        max_count = 442
        operations = plan["arms"] + sum(plan["pilots"].values(), [])
        arm = next(a for a in operations if a["arm_id"] == study_runtime_plan["arm_id"])
        rows = [stream_schedule(plan, sid, arm["rate"]) for sid in range(6)]
        min_step = min(r[i]["schedule_offset_ns"] - r[i-1]["schedule_offset_ns"]
                       for r in rows for i in range(1, len(r)))
    limits = value["admission_limits"]
    _require(type(limits) is dict and limits == {"max_admissions_per_stream": max_count,
              "min_schedule_step_ns": min_step} and
              all(type(item) is int for item in limits.values()),
             "operational admission limits differ from supported original deadlines")
    _require(output_dir.is_dir(), "operational output must be reserved before execution")
    return {"header": header, "output_dir": output_dir}, limits


def require_operational_execution_window_v1(context, *, warmup_s, measurement_s,
        drain_timeout_s, streams, branches):
    if context is None:
        return
    _require(warmup_s == 30.0 and measurement_s == 180.0 and drain_timeout_s == 10.0 and
             streams == 6 and branches == 4,
             "operational source execution differs from the proved frozen window")
