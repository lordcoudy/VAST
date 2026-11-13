#!/usr/bin/env python3
"""Explicit complete real-consumer fixture; artificial observations are not Q1."""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import sys


APPROVED_COMMIT = "299c9c0eefb83fe3031096b0e96527236678a4d2"
GUARDIAN_SOURCE = "scripts/publication_guardian_accepted_policy_preprocessing_contract_v1.py"


def _fixture_source_root_v2(entrypoint: Path) -> Path:
    path = Path(entrypoint)
    if (not path.is_absolute() or not path.is_file() or path.resolve(strict=True) != path
            or path.name not in {"build_production_fixture_v2.py", "build_per_cell_minimum_refusal_v1.py"}):
        raise ValueError("fixture entrypoint origin is missing or noncanonical")
    evidence = path.parent.parent
    change = evidence.parent
    if path.parent.name != "consumer-01" or evidence.name != "evidence":
        raise ValueError("fixture entrypoint evidence layout is unsupported")
    name = "fix-accepted-policy-preprocessing"
    if change.name == name:
        changes = change.parent
    else:
        match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})-" + re.escape(name), change.name)
        if match is None or change.parent.name != "archive":
            raise ValueError("fixture entrypoint change layout is unsupported")
        date.fromisoformat(match[1])
        changes = change.parent.parent
    if changes.name != "changes" or changes.parent.name != "openspec":
        raise ValueError("fixture entrypoint repository layout is unsupported")
    return changes.parent.parent


def _lexical_path_argument(value: str | Path, *, root: Path | None = None) -> Path:
    raw = os.fspath(value)
    path = Path(raw)
    if not raw or ".." in path.parts or raw != os.path.normpath(raw):
        raise ValueError("fixture path argument has noncanonical components")
    if not path.is_absolute():
        if root is None:
            raise ValueError("fixture project root must be an exact absolute path")
        path = root / path
    if root is not None and (path == root or not path.is_relative_to(root)):
        raise ValueError("fixture directory escaped the selected project root")
    return path


def _canonical_fixture_root_v2(value: str | Path, *, source_root: Path) -> Path:
    root = _lexical_path_argument(value)
    if root.resolve(strict=True) != root or not root.is_dir() or root != source_root:
        raise ValueError("fixture project root must be the exact unaliased frozen source root")
    return root


def _canonical_fixture_directory_v2(value: str | Path, *, root: Path, fresh: bool) -> Path:
    path = _lexical_path_argument(value, root=root)
    if fresh:
        if os.path.lexists(path) or path.parent.resolve(strict=True) != path.parent or not path.parent.is_dir():
            raise ValueError("fixture output must be fresh with a canonical physical parent")
    elif path.resolve(strict=True) != path or not path.is_dir():
        raise ValueError("fixture input directory must be canonical and physical")
    return path


def _git(root: Path, *args: str, source_capture=None, slot=None) -> bytes:
    if source_capture is None or slot is None:
        raise ValueError("literal Git requires its explicit fixed source capture")
    return source_capture.git(root, *args, slot=slot)


def _fixture_source_capture_v2(*, project_root, output_dir, capture_dir, deadline,
                               expected_commit, negative=False):
    from tests.fixtures.accepted_policy_literal_source_capture_v2 import LiteralSourceCaptureV2

    return LiteralSourceCaptureV2(project_root=project_root, output_dir=output_dir,
        capture_dir=capture_dir, deadline=deadline, expected_commit=expected_commit, negative=negative)


def _add_fixture_execution_arguments_v2(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--compiler-qualification-json", required=True)
    parser.add_argument("--compiler-admission-json", required=True)
    parser.add_argument("--compiler-deadline-ns", type=int, required=True)
    parser.add_argument("--reader-deadline-json", required=True)
    parser.add_argument("--source-capture-dir", required=True)
    parser.add_argument("--qualification-samples-json")


def _fixture_execution_inputs_v2(args):
    """Read bounded data arguments; existing gates still authenticate authority."""
    from publication_operational_request_domain_v1 import strict_json_object_v1
    from tests.fixtures.accepted_policy_native_fixture_v2 import MAX_FIXTURE_COMPLETED_SAMPLES_PER_BRANCH_V2
    from tests.fixtures.accepted_policy_fixture_compiler_admission_v1 import _compiler_preparation_clock_v1
    from tests.fixtures.accepted_policy_standalone_reader_fixture_v2 import _sealed_deadline_v2

    values = []
    raw_values = [args.compiler_qualification_json, args.compiler_admission_json, args.reader_deadline_json]
    if args.qualification_samples_json is not None:
        raw_values.append(args.qualification_samples_json)
    for raw in raw_values:
        if type(raw) is not str or len(raw) > 4096:
            raise ValueError("fixture execution JSON argument exceeds its bound")
        values.append(strict_json_object_v1(raw.encode("utf-8"), max_bytes=4096))
    qualification, admission, reader_deadline = values[:3]
    overrides = values[3] if len(values) == 4 else None
    if overrides is not None and (len(overrides) > 32 or any(
            type(value) is not int or not 1 <= value <= MAX_FIXTURE_COMPLETED_SAMPLES_PER_BRANCH_V2
            for value in overrides.values())):
        raise ValueError("fixture qualification overrides exceed their count/value bounds")
    _sealed_deadline_v2(reader_deadline)
    _compiler_preparation_clock_v1(args.compiler_deadline_ns)
    return qualification, admission, reader_deadline, overrides


def _fixture_observation_maps_v2(observations: Path):
    from publication_physical_io_v1 import PhysicalRootCustodyV1
    from tests.fixtures.accepted_policy_fixture_compiler_v1 import _json_bound

    values = []
    with PhysicalRootCustodyV1.open(observations, label="fixture producer observations") as custody:
        for name in ("image-inspect-map.json", "device-probe-map.json"):
            _, payload = custody.read_descriptor(observations / name, label=name,
                maximum=16 * 1024**2, capture=True)
            custody.verify()
            value = json.loads(payload)
            del payload
            if type(value) is not dict:
                raise ValueError("fixture observation map requires a JSON object")
            _json_bound(value)
            values.append(value)
    return values[0], values[1]


def _fixture_entrypoint_sha256_v2(root: Path, entrypoint: Path) -> str:
    from publication_physical_io_v1 import PhysicalRootCustodyV1

    with PhysicalRootCustodyV1.open(root, label="fixture producer entrypoint") as custody:
        descriptor, _ = custody.read_descriptor(entrypoint, label="fixture producer entrypoint",
            maximum=2 * 1024**2, capture=False)
        custody.verify()
    return descriptor["sha256"]


class FixtureReportPersistenceRefusedV2(ValueError):
    def __init__(self, facts, *, late=False, clock_error=None):
        self.facts = facts
        self.primary, self.secondary = clock_error, ()
        self.causes = facts["causes"].copy()
        if late and "fixture_report_deadline_exceeded" not in self.causes:
            self.causes.append("fixture_report_deadline_exceeded")
        if clock_error is not None and "fixture_report_clock_unavailable" not in self.causes:
            self.causes.append("fixture_report_clock_unavailable")
        super().__init__("fixture producer report persistence is incomplete")


class _FixtureProducerFailureV2(ValueError):
    def __init__(self, primary, secondary):
        self.primary, self.secondary = primary, tuple(secondary)
        super().__init__("fixture producer failed; distinct finalization causes retained")


def _raise_fixture_producer_failure_v2(primary, secondary):
    distinct = []
    for error in secondary:
        if error is not primary and not any(error is previous for previous in distinct):
            distinct.append(error)
    if distinct:
        raise _FixtureProducerFailureV2(primary, distinct) from primary
    raise primary


def _fresh_json(path: Path, value: object, *, absolute_deadline_ns=None,
                _failure_state=None, _failure_site=None):
    from tests.fixtures.accepted_policy_fixture_report_v1 import REPORT_LIMIT, fixture_report_bytes_v1
    from tests.fixtures.accepted_policy_standalone_reader_fixture_v2 import _monotonic_ns, _write_result_v2

    site = _fixture_report_site_v2(_failure_state, _failure_site)
    if site is not None:
        site.update(entered=True, path=path)
    if (type(absolute_deadline_ns) is not int or absolute_deadline_ns <= 0
            or _monotonic_ns() >= absolute_deadline_ns):
        raise ValueError("fixture report requires an unexpired inherited absolute deadline")

    # Preserve the original text writer's native final newline, including its
    # extra byte on Windows, within the complete physical report ceiling.
    raw = fixture_report_bytes_v1(value, limit=REPORT_LIMIT - (len(os.linesep) - 1))
    raw = raw[:-1] + os.linesep.encode("ascii")
    if site is not None:
        site.update(encoding_complete=True, encoded_bytes=len(raw),
            encoded_sha256=hashlib.sha256(raw).hexdigest())
    if _monotonic_ns() >= absolute_deadline_ns:
        raise ValueError("fixture report deadline expired during encoding")
    if site is not None:
        site["writer_entered"] = True
    facts = _write_result_v2(path, raw, absolute_deadline_ns)
    if site is not None:
        site.update(writer_returned=True, facts=facts)
    try:
        observed = _monotonic_ns()
    except BaseException as clock_error:
        if site is not None:
            site["clock_available"] = False
        raise FixtureReportPersistenceRefusedV2(facts, clock_error=clock_error) from clock_error
    if site is not None:
        site.update(clock_available=True, clock_observed_ns=observed)
    late = observed >= absolute_deadline_ns
    if (facts["attempted"] is not True or type(facts["written_bytes"]) is not int
            or facts["written_bytes"] != len(raw) or facts["write_extent_unknown"] is not False
            or facts["fsync_completed"] is not True or facts["close_completed"] is not True
            or facts["causes"] or late):
        raise FixtureReportPersistenceRefusedV2(facts, late=late)
    return facts


# Fixed diagnostics for the two explicit producer recipes. These are facts, not
# execution authority. Unknown exceptions are deliberately opaque.
_FAILURE_FRAME_LIMIT_V2 = 485376
_FAILURE_REPORT_SITES_V2 = {
    "positive": ("phase00", "phase01", "phase02", "phase03", "stage", "failure"),
    "negative": ("after-proof", "failure", "final"),
}
_FAILURE_SOURCE_SLOTS_V2 = {
    "positive": ("head", "status", "guardian"),
    "negative": ("before-head", "before-status", "before-proof", "after-proof", "after-head", "after-status"),
}
_FAILURE_WRITER_CODES_V2 = (
    "result_deadline", "result_open", "result_short_write", "result_write",
    "result_fsync", "result_close", "result_deadline_exceeded",
)
_FAILURE_SOURCE_CODES_V2 = (
    "source_post_return_clock", "source_result_persistence_raised",
    "source_observation_deadline", "source_capture_or_persistence_incomplete",
    "source_completed_file_or_protocol_refused",
)


def _fixture_failure_state_v2(recipe):
    if type(recipe) is not str or recipe not in _FAILURE_REPORT_SITES_V2:
        raise ValueError("unknown fixed fixture failure recipe")
    return {"recipe": recipe, "source_context": None, "assessment": None,
        "assessment_returned": False, "assessment_failure_report_prepared": False,
        "cold_reader": None, "reader_output_dir": None, "parser_exit": None,
        "parser_status": None, "reports": {name: {
            "entered": False, "path": None, "encoding_complete": False,
            "encoded_bytes": None, "encoded_sha256": None, "writer_entered": False,
            "writer_returned": False, "facts": None, "clock_available": None,
            "clock_observed_ns": None} for name in _FAILURE_REPORT_SITES_V2[recipe]}}


def _fixture_report_context_v2(state, site):
    return {} if state is None else {"_failure_state": state, "_failure_site": site}


def _fixture_report_site_v2(state, site):
    if state is None:
        return None
    if (type(state) is not dict or type(site) is not str
            or type(state.get("recipe")) is not str
            or state["recipe"] not in _FAILURE_REPORT_SITES_V2
            or site not in _FAILURE_REPORT_SITES_V2[state["recipe"]]
            or type(state.get("reports")) is not dict):
        raise ValueError("unknown fixed fixture report site")
    record = state["reports"].get(site)
    if type(record) is not dict or record.get("entered") is not False:
        raise ValueError("fixture report site is malformed or reused")
    return record


def _fixture_loaded_type_v2(module_name, class_name):
    from types import ModuleType
    module = sys.modules.get(module_name)
    if type(module) is ModuleType:
        return vars(module).get(class_name)
    return None


def _fixture_error_kind_v2(error):
    kind = type(error)
    if kind is _FixtureProducerFailureV2:
        return "producer_failure"
    if kind is FixtureReportPersistenceRefusedV2:
        return "report_persistence"
    for module, name, code in (
        ("accepted_policy_literal_source_capture_v2", "LiteralSourceCaptureRefusedV2", "literal_source"),
        ("accepted_policy_physical_fixture_v2", "_FixturePreparationCleanupErrorV2", "preparation_cleanup"),
        ("accepted_policy_physical_fixture_v2", "_FixtureCapturedEngineErrorV2", "captured_engine"),
        ("accepted_policy_guardian_journal_fixture_v1", "_FixtureJournalIoErrorV1", "journal_io"),
        ("accepted_policy_standalone_reader_fixture_v2", "StandaloneReaderRefusedV2", "standalone_reader"),
        ("accepted_policy_native_fixture_v2", "_FixtureSidecarWriteErrorV2", "sidecar_write"),
        ("accepted_policy_fixture_compiler_v1", "FixtureCompilerError", "compiler"),
    ):
        if kind is _fixture_loaded_type_v2("tests.fixtures." + module, name):
            return code
    return "opaque_exception"


def _fixture_failure_report_v2(report, error, state):
    # This precedes the report's own writer and remaining source cleanup.
    value = {**report, "failure": {"kind": _fixture_error_kind_v2(error),
        "final_state_observed": False}, "campaign_authority": False}
    if state is not None and (state["assessment_returned"] is True or state["assessment"] is not None):
        value["actual_f1_assessment"] = state["assessment"]
        state["assessment_failure_report_prepared"] = True
    return value


def _fixture_failure_frame_v2(error, state):
    from pathlib import PosixPath, PurePosixPath, PureWindowsPath, WindowsPath
    from tests.fixtures.accepted_policy_fixture_report_v1 import fixture_report_bytes_v1

    refusals, files, captures, source_slots, report_sites, errors = [], [], [], [], [], []
    capture_objects, error_objects = [], []
    compiler_object, sidecar_object, reader_object = None, None, None
    compiler_block, sidecar_block, reader_block = None, None, None

    def refuse(code):
        # All callers use fixed literals; no error text can enter the header.
        if code not in refusals:
            if len(refusals) >= 32:
                raise ValueError("fixture projection refusal roster exceeded")
            refusals.append(code)
        return None

    def plain(value, maximum=64):
        if (type(value) is not dict or len(value) > maximum
                or any(type(key) is not str for key in value)):
            refuse("invalid_owned_mapping")
            return {}
        return value

    def integer(value, *, nullable=False, nonnegative=False):
        if value is None and nullable:
            return None
        if type(value) is int and -(2**63) <= value < 2**63 and (not nonnegative or value >= 0):
            return value
        return refuse("invalid_integer")

    def boolean(value, *, nullable=False):
        if value is None and nullable:
            return None
        if type(value) is bool:
            return value
        return refuse("invalid_boolean")

    def digest(value, *, nullable=False):
        if value is None and nullable:
            return None
        if type(value) is str and len(value) == 64 and all(char in "0123456789abcdef" for char in value):
            return value
        return refuse("invalid_digest")

    def codes(value, *, maximum=64, width=128, whitelist=None):
        if not (type(value) is list or type(value) is tuple) or len(value) > maximum:
            return refuse("invalid_cause_codes")
        for item in value:
            if (type(item) is not str or not 1 <= len(item) <= width
                    or any(not 32 <= ord(char) <= 126 or char in '\\"' for char in item)
                    or whitelist is not None and item not in whitelist):
                return refuse("invalid_cause_codes")
        return list(value)

    def fit(value, limit):
        try:
            fixture_report_bytes_v1(value, limit=limit + 1)
        except BaseException:
            return refuse("projection_block_overflow")
        return value

    def path_text(value):
        kind = type(value)
        if any(kind is supported for supported in (PosixPath, WindowsPath, PurePosixPath, PureWindowsPath)):
            parts = value.parts
            if len(parts) > 640 or any(type(part) is not str for part in parts) or sum(map(len, parts)) > 640:
                return refuse("invalid_file_path")
            value = str(value)  # Exact stdlib path only, never arbitrary __fspath__.
        if type(value) is not str or not 1 <= len(value) <= 640:
            return refuse("invalid_file_path")
        return value

    def file_ref(path, role, metadata=None):
        text = path_text(path)
        if text is None:
            return None
        if len(files) >= 22:
            return refuse("file_reference_limit")
        row = {"id": len(files), "role": role, "path": text, **(metadata or {})}
        # Charge every non-path byte, including its key, braces and separators.
        without_path = {**row, "path": ""}
        if (len(fixture_report_bytes_v1(without_path)) - 3 > 510
                or fit(row, 8192) is None):
            return refuse("file_reference_limit")
        files.append(row)
        return row["id"]

    def persistence(value):
        if value is None:
            return None
        row = plain(value)
        return {"attempted": boolean(row.get("attempted")),
            "written_bytes": integer(row.get("written_bytes"), nonnegative=True),
            "write_extent_unknown": boolean(row.get("write_extent_unknown")),
            "fsync_completed": boolean(row.get("fsync_completed")),
            "close_completed": boolean(row.get("close_completed")),
            "causes": codes(row.get("causes"), maximum=8, width=24, whitelist=_FAILURE_WRITER_CODES_V2)}

    def capture(value, role):
        if value is None:
            return None
        for index, previous in enumerate(capture_objects):
            if value is previous:
                return index
        if len(captures) >= 6:
            return refuse("capture_limit")
        row = plain(value)
        index = len(captures)
        capture_objects.append(value)
        captures.append(None)
        deadline, closure = plain(row.get("deadline")), plain(row.get("closure"))
        identities = closure.get("owned_descendants")
        if type(identities) is not list or len(identities) > 64:
            identities = refuse("identity_limit")
        else:
            identities = [{"pid": integer(plain(item).get("pid"), nonnegative=True),
                "start_ticks": integer(plain(item).get("start_ticks"), nonnegative=True)} for item in identities]
        projected = {"role": role, "causes": codes(row.get("causes")),
            "deadline": {key: integer(deadline.get(key), nonnegative=True) for key in (
                "absolute_monotonic_ns", "term_grace_ns", "kill_grace_ns", "final_ns", "observe_end_ns")},
            "pid": integer(row.get("pid"), nullable=True, nonnegative=True),
            "start_ticks": integer(row.get("start_ticks"), nullable=True, nonnegative=True),
            "returncode": integer(row.get("returncode"), nullable=True),
            "signal": integer(row.get("signal"), nullable=True, nonnegative=True),
            "forced": boolean(row.get("forced")), "term_sent": boolean(row.get("term_sent")),
            "kill_sent": boolean(row.get("kill_sent")),
            "term_delivered": integer(row.get("term_delivered"), nonnegative=True),
            "kill_delivered": integer(row.get("kill_delivered"), nonnegative=True),
            "closure": {"closed": boolean(closure.get("closed")),
                "owned_descendants": identities, "descendants_unknown": boolean(closure.get("descendants_unknown")),
                "subreaper_restored": boolean(closure.get("subreaper_restored"))}}
        for name in ("stdout", "stderr"):
            current = row.get(name)
            if current is None:
                projected[name] = None
                continue
            channel, raw_file = plain(current), plain(plain(current).get("file"))
            reference = file_ref(raw_file.get("path"), role + "/" + name, {
                "written_bytes": integer(raw_file.get("written_bytes"), nonnegative=True),
                "write_extent_unknown": boolean(raw_file.get("write_extent_unknown")),
                "confirmed_prefix_sha256": digest(raw_file.get("sha256"), nullable=True),
                "fsync_completed": boolean(raw_file.get("fsync_completed")),
                "close_completed": boolean(raw_file.get("close_completed"))})
            projected[name] = {"observed_bytes": integer(channel.get("observed_bytes"), nonnegative=True),
                "retained_bytes": integer(channel.get("retained_bytes"), nonnegative=True),
                "discarded_bytes": integer(channel.get("discarded_bytes"), nullable=True, nonnegative=True),
                "remainder_unknown": boolean(channel.get("remainder_unknown")),
                "eof": boolean(channel.get("eof")), "overflow": boolean(channel.get("overflow")),
                "retained_sha256": digest(channel.get("retained_sha256"), nullable=True), "file": reference}
        captures[index] = fit(projected, 18432)
        return index

    state = plain(state)
    recipe = state.get("recipe")
    if type(recipe) is not str or recipe not in _FAILURE_REPORT_SITES_V2:
        raise ValueError("invalid fixed fixture failure state")
    slots = _FAILURE_SOURCE_SLOTS_V2[recipe]
    records, used = [], []
    context = state.get("source_context")
    source_type = _fixture_loaded_type_v2("tests.fixtures.accepted_policy_literal_source_capture_v2",
        "LiteralSourceCaptureV2")
    if context is not None:
        if type(context) is source_type:
            records, used = context.records, context.used
        else:
            refuse("source_context_unavailable")
    if type(records) is not list or len(records) > len(slots):
        records = []
        refuse("source_record_limit")
    if (type(used) is not list or len(used) > len(slots)
            or any(type(item) is not str or item not in slots for item in used)):
        used = []
        refuse("source_record_limit")

    # Gather owned graph first, recovering only fixed owned carriers when main did
    # not receive a context or reader return. No __cause__/__context__ traversal.
    def visit(current, depth):
        nonlocal compiler_object, sidecar_object, reader_object, records
        if current is None:
            return None
        for index, previous in enumerate(error_objects):
            if current is previous:
                return index
        if depth >= 8 or len(errors) >= 64:
            return refuse("error_graph_limit")
        index = len(errors)
        error_objects.append(current)
        kind = _fixture_error_kind_v2(current)
        node = {"kind": kind, "primary": None, "secondary": [], "fact_role": None}
        errors.append(node)
        if kind not in ("compiler", "opaque_exception"):
            try:
                cleanup = object.__getattribute__(current, "fixture_cleanup_causes")
            except AttributeError:
                node["fixture_cleanup_causes_available"] = False
                node["fixture_cleanup_causes"] = None
            else:
                node["fixture_cleanup_causes_available"] = True
                cleanup = codes(cleanup, maximum=2, width=128)
                if cleanup is not None and any(not code.startswith((
                        "fixture_socket_close_", "fixture_elf_close_")) for code in cleanup):
                    cleanup = refuse("invalid_cleanup_codes")
                node["fixture_cleanup_causes"] = cleanup
        if kind == "compiler":
            if compiler_object is None:
                compiler_object = current
                node["fact_role"] = "compiler"
            elif current is not compiler_object:
                refuse("extra_compiler_terminal")
            errors[index] = fit(node, 2048)
            return index
        if kind == "opaque_exception":
            refuse("opaque_exception_facts_unavailable")
            errors[index] = fit(node, 2048)
            return index
        if kind == "sidecar_write":
            if sidecar_object is None:
                sidecar_object = current
                node["fact_role"] = "sidecar"
            elif current is not sidecar_object:
                refuse("extra_sidecar_terminal")
        elif kind == "literal_source":
            node["fact_role"] = "source_slots"
            if not records:
                evidence = plain(current.evidence)
                fallback = evidence.get("records")
                if fallback is None and type(evidence.get("slot")) is str:
                    fallback = [evidence]
                if type(fallback) is list and len(fallback) <= len(slots):
                    records = fallback
                else:
                    refuse("source_records_unavailable")
        elif kind == "standalone_reader":
            if reader_object is None:
                reader_object = current.evidence
                node["fact_role"] = "reader"
            elif current.evidence is not reader_object:
                refuse("extra_reader_terminal")
            errors[index] = fit(node, 2048)
            return index
        elif kind == "report_persistence":
            matching = [name for name, record in plain(state.get("reports")).items()
                if type(record) is dict and record.get("facts") is current.facts]
            if len(matching) == 1 and matching[0] in _FAILURE_REPORT_SITES_V2[recipe]:
                node["fact_role"] = matching[0]
            else:
                refuse("report_facts_unavailable")
            node["causes"] = codes(current.causes, maximum=10, width=64,
                whitelist=(*_FAILURE_WRITER_CODES_V2, "fixture_report_deadline_exceeded", "fixture_report_clock_unavailable"))
        primary = current.primary
        node["primary"] = visit(primary, depth + 1)
        secondary = current.secondary
        if not (type(secondary) is tuple or type(secondary) is list) or len(secondary) > 8:
            refuse("secondary_limit")
        else:
            distinct = []
            for child in secondary:
                if child is None or child is primary or any(child is previous for previous in distinct):
                    continue
                distinct.append(child)
                child_index = visit(child, depth + 1)
                if child_index is not None:
                    node["secondary"].append(child_index)
        errors[index] = fit(node, 2048)
        return index

    visit(error, 0)
    for slot in slots:
        matching = []
        for candidate in records:
            candidate = plain(candidate)
            candidate_slot = candidate.get("slot")
            if type(candidate_slot) is not str or candidate_slot not in slots:
                refuse("source_record_slot")
            elif candidate_slot == slot:
                matching.append(candidate)
        if len(matching) > 1:
            refuse("source_record_slot")
        row = matching[0] if len(matching) == 1 else None
        projected = {"slot": slot, "used": slot in used or row is not None,
            "record_available": row is not None, "capture": None}
        if row is not None:
            projected.update(capture=capture(row.get("capture"), "source/" + slot),
                capture_returned=boolean(row.get("capture_returned")),
                capture_return_observed_ns=integer(row.get("capture_return_observed_ns"), nullable=True, nonnegative=True),
                post_return_clock_failed=boolean(row.get("post_return_clock_failed")),
                returned_within_observation=boolean(row.get("returned_within_observation"), nullable=True),
                result_complete=boolean(row.get("result_complete")),
                result_persistence=persistence(row.get("result_persistence")),
                causes=codes(row.get("causes"), maximum=8, width=64, whitelist=_FAILURE_SOURCE_CODES_V2),
                result=file_ref(row.get("result_path"), "source/" + slot + "/result",
                    {"intended_encoded_sha256": digest(row.get("result_sha256"), nullable=True)}))
        elif slot in used:
            refuse("source_records_unavailable")
        source_slots.append(fit(projected, 2048))

    reports = plain(state.get("reports"))
    for name in _FAILURE_REPORT_SITES_V2[recipe]:
        row = plain(reports.get(name))
        returned = boolean(row.get("writer_returned"))
        projected = {"site": name, "entered": boolean(row.get("entered")),
            "encoding_complete": boolean(row.get("encoding_complete")),
            "encoded_bytes": integer(row.get("encoded_bytes"), nullable=True, nonnegative=True),
            "encoded_sha256": digest(row.get("encoded_sha256"), nullable=True),
            "writer_entered": boolean(row.get("writer_entered")), "writer_returned": returned,
            "persistence": persistence(row.get("facts")) if returned is True else None,
            "clock_available": boolean(row.get("clock_available"), nullable=True),
            "clock_observed_ns": integer(row.get("clock_observed_ns"), nullable=True, nonnegative=True),
            "file": file_ref(row.get("path"), "report/" + name,
                {"intended_target_only": True}) if row.get("path") is not None else None}
        report_sites.append(fit(projected, 2048))

    actual_reader = state.get("cold_reader")
    if actual_reader is not None:
        if reader_object is not None and reader_object is not actual_reader:
            refuse("extra_reader_terminal")
        reader_object = actual_reader
    reader_directory = state.get("reader_output_dir")
    if reader_object is not None or reader_directory is not None or recipe == "positive":
        row = plain(reader_object) if reader_object is not None else {}
        text = path_text(reader_directory) if reader_directory is not None else None
        target = None
        if text is not None:
            target = file_ref(text.rstrip("/\\") + "/standalone-guardian-cold-reader.result.v2.json",
                "reader/result", {"intended_target_only": True})
        if reader_object is None and reader_directory is not None:
            refuse("reader_facts_unavailable")
        if reader_object is not None and reader_directory is None:
            refuse("reader_target_unavailable")
        reader_block = fit({"call_site_entered": True if reader_directory is not None else
                None if reader_object is not None else False,
            "returned_evidence_available": reader_object is not None,
            "capture": capture(row.get("capture"), "reader"),
            "passed": boolean(row.get("standalone_guardian_cold_reader_passed"), nullable=True),
            "result_complete": boolean(row.get("result_complete"), nullable=True),
            "result_persistence": persistence(row.get("result_persistence")), "intended_result": target}, 2048)
        if recipe != "positive":
            refuse("reader_recipe_mismatch")

    if compiler_object is not None:
        try:
            facts = object.__getattribute__(compiler_object, "facts")
        except AttributeError:
            facts_kind = "absent"
        else:
            facts_kind = "null" if facts is None else "exact_dict" if type(facts) is dict else "other"
        compiler_block = fit({"causes": codes(compiler_object.causes),
            "facts_kind": facts_kind, "facts_reference": None, "heterogeneous_facts_qualified": False}, 16384)
        if facts_kind in ("exact_dict", "other"):
            refuse("compiler_facts_unqualified")

    if sidecar_object is not None:
        native_module = sys.modules["tests.fixtures.accepted_policy_native_fixture_v2"]
        specs = vars(native_module)["_FIXTURE_SIDECAR_SPECS_V2"]
        def table(value):
            row = plain(value)
            filename = row.get("filename")
            if type(filename) is not str or len(filename) > 64 or filename not in specs:
                return refuse("invalid_sidecar_table")
            admitted = integer(row.get("admitted_upper_bytes"), nonnegative=True)
            accepted = integer(row.get("accepted_text_bytes"), nonnegative=True)
            if admitted is None or accepted is None or not accepted <= admitted <= specs[filename][-1]:
                return refuse("invalid_sidecar_extent")
            stage = row.get("failure_stage")
            if stage is not None and (type(stage) is not str or stage not in (
                    "dataframe", "open", "write", "flush", "fsync", "close")):
                stage = refuse("invalid_sidecar_table")
            result = {"filename": filename, "admitted_upper_bytes": admitted,
                "accepted_text_bytes": accepted, "failure_stage": stage}
            for flag in ("open_completed", "serialization_completed", "flush_completed",
                    "fsync_completed", "close_attempted", "close_completed", "write_extent_unknown"):
                result[flag] = boolean(row.get(flag))
            return fit(result, 1024)
        completed = plain(sidecar_object.completed, 11)
        prior = []
        for name, facts in completed.items():
            facts = plain(facts)
            filename = facts.get("filename")
            if type(filename) is not str or len(filename) > 64 or filename != name:
                refuse("invalid_sidecar_table")
            else:
                prior.append(table(facts))
        try:
            directory = object.__getattribute__(sidecar_object, "output_directory")
        except AttributeError:
            reference = refuse("sidecar_directory_unavailable")
        else:
            reference = file_ref(directory, "sidecar/directory", {"intended_target_only": True})
        sidecar_block = fit({"directory": reference, "failed": table(sidecar_object.facts),
            "completed": prior, "text_acceptance_is_disk_extent": False}, 16384)
        if reader_object is not None or reader_directory is not None:
            refuse("sidecar_reader_overlap")

    assessment = state.get("assessment")
    passed = plain(assessment).get("passed") if type(assessment) is dict else None
    if passed is not None and type(passed) is not bool:
        passed = refuse("invalid_assessment_status")
    header = {"schema_version": 2, "kind": "fixture_producer_failure",
        "recipe": recipe, "campaign_authority": False, "physical_acceptance": False,
        "facts_complete": not refusals, "projection_refusals": refusals,
        "assessment_available": state.get("assessment_returned") is True or assessment is not None,
        "assessment_passed": passed,
        "assessment_failure_report_site": "failure"
            if state.get("assessment_failure_report_prepared") is True else None}
    if fit(header, 4095) is None:
        raise ValueError("fixture failure header exceeds its fixed allowance")
    frame = {**header, "files": files, "captures": captures, "source_slots": source_slots,
        "report_sites": report_sites, "reader": reader_block, "compiler": compiler_block,
        "sidecar": sidecar_block, "errors": errors}
    return fixture_report_bytes_v1(frame, limit=_FAILURE_FRAME_LIMIT_V2)


def _fixture_argument_parser_v2(state, **kwargs):
    if state is None:
        return argparse.ArgumentParser(**kwargs)

    class Parser(argparse.ArgumentParser):
        def exit(self, status=0, message=None):
            error = SystemExit(status)
            state["parser_exit"], state["parser_status"] = error, status
            raise error

        def error(self, message):
            self.exit(2)

    kwargs.setdefault("prog", "fixture-producer-" + state["recipe"])
    return Parser(**kwargs)


def _fixture_cli_v2(entrypoint, recipe):
    state = _fixture_failure_state_v2(recipe)
    try:
        entrypoint(_failure_state=state)
        return 0
    except BaseException as error:
        originated = error is state["parser_exit"]
        status = state["parser_status"] if originated else 1
        if type(status) is not int or not 0 <= status <= 255:
            status = 1
        if originated and status == 0:
            return 0
        if status == 0:
            status = 1
        try:
            raw = _fixture_failure_frame_v2(error, state)
        except BaseException:
            raw = (b'{"campaign_authority":false,"facts_complete":false,'
                b'"kind":"fixture_producer_failure","physical_acceptance":false,'
                b'"projection_refusals":["frame_unavailable"],"schema_version":2}\n')
        try:
            count = os.write(2, raw)
        except BaseException:
            return 1
        return status if type(count) is int and count == len(raw) else 1


def main(*, _failure_state=None) -> None:
    parser = _fixture_argument_parser_v2(_failure_state, description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--artifact-base", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--socket-prefix", default=".apfv2")
    parser.add_argument("--samples-per-branch", type=int, default=30)
    parser.add_argument("--stage", choices=("inputs", "original-observations", "complete"), default="complete")
    _add_fixture_execution_arguments_v2(parser)
    args = parser.parse_args()
    source_root = _fixture_source_root_v2(Path(__file__))
    root = _canonical_fixture_root_v2(args.project_root, source_root=source_root)
    if re.fullmatch(r"[0-9a-f]{40}", args.expected_source_commit) is None:
        raise ValueError("expected source commit must be an exact commit SHA")
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "scripts"))
    from tests.fixtures.accepted_policy_native_fixture_v2 import MAX_FIXTURE_COMPLETED_SAMPLES_PER_BRANCH_V2

    qualification, admission, reader_deadline, overrides = _fixture_execution_inputs_v2(args)
    if (type(args.samples_per_branch) is not int or args.samples_per_branch < 30
            or args.samples_per_branch > MAX_FIXTURE_COMPLETED_SAMPLES_PER_BRANCH_V2):
        raise ValueError("complete fixture requires 30..985 samples in every branch cell")
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,100}", args.namespace) is None:
        raise ValueError("fixture upstream namespace is invalid")
    base = _canonical_fixture_directory_v2(args.artifact_base, root=root, fresh=False)
    output = _canonical_fixture_directory_v2(args.output_dir, root=root, fresh=True)
    context = _fixture_source_capture_v2(project_root=root, output_dir=output, capture_dir=args.source_capture_dir,
        deadline=reader_deadline, expected_commit=args.expected_source_commit)
    if _failure_state is not None:
        _failure_state["source_context"] = context
    with context as source_capture:
        _run_fixture_v2(args, root, qualification, admission, reader_deadline, overrides, base, output,
            source_capture, **({} if _failure_state is None else {"_failure_state": _failure_state}))


def _run_fixture_v2(args, root, qualification, admission, reader_deadline, overrides, base, output,
                    source_capture, *, _failure_state=None):
    if _git(root, "rev-parse", "HEAD", source_capture=source_capture, slot="head").decode().strip() != args.expected_source_commit:
        raise ValueError("fixture source HEAD differs from the explicitly pinned commit")
    if _git(root, "status", "--porcelain", "--untracked-files=no", source_capture=source_capture, slot="status"):
        raise ValueError("fixture tracked source is not clean")
    from tests.fixtures.accepted_policy_fixture_provenance_v1 import loaded_fixture_production_sources_v1
    from tests.fixtures.accepted_policy_physical_fixture_v2 import (
        _fixture_operation_sample_counts_v2, build_original_native_fixture_observations_v2,
        prepared_complete_fixture_inputs_v2,
    )
    from tests.fixtures.accepted_policy_consumer_fixture_v2 import complete_fixture_production_consumers_v2

    original_sources = loaded_fixture_production_sources_v1(project_root=root)
    approved_source = _git(root, "show", APPROVED_COMMIT + ":" + GUARDIAN_SOURCE,
        source_capture=source_capture, slot="guardian")
    report = {"schema_version": 2, "fixture_stage": args.stage,
              "campaign_authority": False, "physical_inference_observed": False,
              "complete_consumer_positive_asserted": False,
              "upstream_root": str(root), "source_commit": args.expected_source_commit,
              "entrypoint_sha256": _fixture_entrypoint_sha256_v2(root, Path(__file__)),
              "samples_per_branch": args.samples_per_branch,
              "expected_measured_sample_count": 32 * 4 * args.samples_per_branch if overrides is None else None,
              "approved_old_guardian_commit": APPROVED_COMMIT,
              "approved_old_guardian_source_sha256": hashlib.sha256(approved_source).hexdigest(),
              "initial_loaded_production_sources": original_sources}

    def phase(name: str) -> None:
        current = loaded_fixture_production_sources_v1(project_root=root)
        by_name = {row["module"]: row for row in current}
        if any(by_name.get(row["module"]) != row for row in original_sources):
            raise ValueError("previously loaded production source changed during the fixture")
        print(json.dumps({"fixture_phase": name, "output_dir": str(output),
                          "production_module_count": len(current)}, sort_keys=True), flush=True)
        if output.is_dir():
            _fresh_json(output / ("producer-phase-" + name + ".v2.json"),
                        {"phase": name, "source_commit": args.expected_source_commit,
                         "loaded_production_sources": current, "campaign_authority": False},
                        absolute_deadline_ns=reader_deadline["absolute_monotonic_ns"],
                        **_fixture_report_context_v2(_failure_state, "phase" + name[:2]))

    phase("00-imported")
    config_base = root / "configs" / f"checkpoint_analytics_model_parity.refreshed.v4.{args.namespace}.accepted"
    observations = base / "consumer-runtime-observations-02"
    try:
        image_inspections, device_probes = _fixture_observation_maps_v2(observations)
        with prepared_complete_fixture_inputs_v2(
            project_root=root, output_dir=output,
            identity_patch_path=base / "qualification_image_identity_patch.json",
            accepted_model_parity_manifest_path=config_base.with_suffix(".accepted.yaml"),
            accepted_model_parity_assessment_path=Path(str(config_base) + ".assessment.json"),
            accepted_model_parity_receipt_path=Path(str(config_base) + ".acceptance_receipt.json"),
            image_inspections=image_inspections, device_probes=device_probes,
            socket_prefix=args.socket_prefix,
            compiler_qualification=qualification, compiler_admission=admission,
            compiler_absolute_deadline_ns=args.compiler_deadline_ns,
        ) as prepared:
            sample_counts = _fixture_operation_sample_counts_v2(prepared["capture_plan"],
                samples_per_branch=args.samples_per_branch, qualification_samples_by_operation_id=overrides)
            report["expected_measured_sample_count"] = 4 * sum(
                sample_counts[row["operation_id"]] for row in prepared["capture_plan"]["operation_manifest"]["operations"]
                if row["phase"] == "qualification_cell")
            phase("01-prepared")
            report.update(transaction_receipt=str(prepared["transaction"]["transaction_receipt_path"]),
                          preprocessing_receipt=str(prepared["preprocessing"]["receipt_path"]),
                          capture_plan=prepared["capture_plan_descriptor"],
                          runtime_input_receipt=str(prepared["runtime"]["receipt_path"]))
            if args.stage != "inputs":
                native = build_original_native_fixture_observations_v2(prepared=prepared,
                    samples_per_branch=args.samples_per_branch, qualification_samples_by_operation_id=overrides)
                phase("02-originals")
                report.update(original_operation_count=len(native["operations"]),
                              qualification_count=native["qualification_count"], native_domains=native["native_domains"])
                if args.stage == "complete":
                    consumers = complete_fixture_production_consumers_v2(
                        prepared=prepared, native=native, approved_guardian_source=approved_source,
                        approved_guardian_commit=APPROVED_COMMIT,
                        standalone_reader_deadline=reader_deadline,
                        **({} if _failure_state is None else {"_failure_state": _failure_state}),
                    )
                    if consumers["assessment"]["coverage"]["accepted_sample_count"] != report["expected_measured_sample_count"]:
                        raise ValueError("real F1 measured sample count includes a drop or loses a branch cell")
                    phase("03-complete-consumers")
                    report.update(consumers=consumers, complete_consumer_positive_asserted=True)
            report["final_loaded_production_sources"] = loaded_fixture_production_sources_v1(project_root=root)
            _fresh_json(output / "producer-stage-report.v2.json", report,
                        absolute_deadline_ns=reader_deadline["absolute_monotonic_ns"],
                        **_fixture_report_context_v2(_failure_state, "stage"))
            print(json.dumps({"fixture_completed": args.stage,
                              "complete_consumer_positive_asserted": report["complete_consumer_positive_asserted"],
                              "report_path": str(output / "producer-stage-report.v2.json")}, sort_keys=True), flush=True)
    except Exception as error:
        try:
            if output.is_dir() and not (output / "producer-failure.v2.json").exists():
                _fresh_json(output / "producer-failure.v2.json",
                            _fixture_failure_report_v2({**report, "complete_consumer_positive_asserted": False},
                                error, _failure_state),
                            absolute_deadline_ns=reader_deadline["absolute_monotonic_ns"],
                            **_fixture_report_context_v2(_failure_state, "failure"))
        except BaseException as secondary:
            _raise_fixture_producer_failure_v2(error, [secondary])
        raise


if __name__ == "__main__":
    raise SystemExit(_fixture_cli_v2(main, "positive"))
