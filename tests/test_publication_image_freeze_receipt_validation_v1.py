from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
LEAF_NAME = "publication_image_freeze_receipt_validation_v1"
BUILDER_NAME = "publication_image_build_v1.py"
MATERIALIZER_NAME = "materialize_runtime_build_context_v3.py"
RECEIPT_KIND = "vast_publication_image_freeze_receipt_v1"
STOCK_BUILDER_SHA256 = "7a8d6cf67de32515cf330073f3933b7af4216e552c5d606e8a17df500cf7938a"
STOCK_REFREEZE_SHA256 = "38757bd592fed2c137325f0f4b320812145ac64a2a78550a85e549bf0a0cbb8a"
STOCK_FUNCTION_SHA256 = "ee3983227737448ff600f4f6524cac336a51844e4f5f077f056052294849e201"
STOCK_READER_SOURCE = '''def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)
def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
def _receipt_sha256(payload: Mapping[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("receipt_sha256", None)
    return hashlib.sha256(_canonical_json(unsigned)).hexdigest()
def load_publication_image_freeze_receipt(path: Path) -> dict[str, object]:
    receipt_path = Path(path)
    info = receipt_path.lstat()
    _require(stat.S_ISREG(info.st_mode) and not receipt_path.is_symlink() and int(info.st_nlink) == 1, "producer receipt must be a physical single-link file")
    try:
        data = json.loads(receipt_path.read_bytes())
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("producer receipt is not valid JSON") from error
    _require(isinstance(data, dict) and data.get("artifact_kind") == RECEIPT_KIND and data.get("schema_version") == 1, "producer receipt envelope drifted")
    _require(type(data.get("receipt_sha256")) is str and data["receipt_sha256"] == _receipt_sha256(data), "producer receipt self-identity drifted")
    _require(isinstance(data.get("images"), list), "producer receipt images are invalid")
    return data
'''


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _signed(value: dict[str, object]) -> dict[str, object]:
    result = dict(value)
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = hashlib.sha256(_canonical(result)).hexdigest()
    return result


# These children use real read-only production functions. No build/capture,
# Docker, parity, assessment or dependency substitution is involved.
PREPARE_CHILD = r'''
import hashlib, json, sys
from pathlib import Path
authority, project, directory = map(Path, sys.argv[1:4])
sys.path.insert(0, str(authority / "scripts"))
# Native physical custody's pure source closure lives in the preserved input
# tree. This fixture-generation process is separate from the packaged child.
sys.path.append(str(project / "scripts"))
import publication_qualification_image_refreeze_v1 as refreeze
directory.mkdir(exist_ok=False)
def emit(name, value):
    path = directory / name
    path.write_bytes(refreeze._canonical(value) + b"\n")
    return path
build_sha = hashlib.sha256((project / refreeze.BUILD_REGISTRY_RELATIVE_PATH).read_bytes()).hexdigest()
registry_sha = hashlib.sha256((project / refreeze.REGISTRY_RELATIVE_PATH).read_bytes()).hexdigest()
def producer(group, images):
    value = {"artifact_kind": refreeze.BUILD_RECEIPT_KIND, "schema_version": 1,
             "group": group, "registry_path": refreeze.BUILD_REGISTRY_RELATIVE_PATH,
             "registry_sha256": build_sha, "images": images}
    value["receipt_sha256"] = refreeze.self_sha256(value, "receipt_sha256")
    return value
native_ids = {"native_probe_deepstream": "sha256:" + "1" * 64,
              "native_probe_openvino": "sha256:" + "2" * 64,
              "native_probe_savant": "sha256:" + "3" * 64}
native = emit("native.json", producer("native_probe", [
    {"name": name, "image_id": image_id} for name, image_id in native_ids.items()]))
workers = emit("workers.json", producer("analytics_worker", [
    {"name": "analytics_worker_openvino", "image_id": "sha256:" + "4" * 64,
     "base_image_id": native_ids["native_probe_openvino"], "identity_changed": False},
    {"name": "analytics_worker_tensorrt", "image_id": "sha256:" + "5" * 64,
     "base_image_id": native_ids["native_probe_deepstream"], "identity_changed": False}]))
repositories = {"deepstream": "vast/deepstream-publication-runtime-v3",
                "savant": "vast/savant-publication-runtime-v3",
                "openvino_gva": "vast/openvino-gva-publication-runtime-v3",
                "gstreamer_custom": "vast/gstreamer-custom-publication-runtime-v3"}
runtimes = {}
for number, system in enumerate(refreeze.SYSTEMS, start=6):
    digit = str(number)
    image_id = "sha256:" + digit * 64
    repository = repositories[system]
    final = repository + ":materialized"
    canonical = repository + "@" + image_id
    physical = {
        "final_reference": final,
        "deterministic_references": [final + "-determinism-a", final + "-determinism-b"],
        "image_id": image_id, "observed_repository_digests": [canonical],
        "canonical_repository_digest": canonical, "canonical_repository_digest_observed": True,
        "inspect_projection_sha256": digit * 64, "inspect_full_sha256": digit * 64,
        "architecture": "amd64", "os": "linux", "created": "1970-01-01T00:00:00Z",
        "entrypoint": ["/runtime"], "user": "root", "labels": {},
        "base": {"kind": "remote_digest", "image_id": "sha256:" + "a" * 64},
        "native_builder": None, "native_receipt": None,
        "source_identity": {
            "runtime_source_sha256": digit * 64, "runtime_source_count": 1,
            "dependency_set_sha256": digit * 64, "dependency_count": 1,
            "source_allowlist_sha256": digit * 64,
            "source_allowlist": {"path": "allowlist.txt", "size": 1, "sha256": digit * 64},
            "native_source_sha256": None, "native_source_count": 0},
        "embedded_files": {"/runtime": digit * 64},
        "embedded_aliases": {"runtime_entrypoint": {"path": "/runtime", "sha256": digit * 64}},
        "embedded_set_sha256": digit * 64}
    value = {"schema_version": 1, "artifact_kind": refreeze.RUNTIME_RECEIPT_KIND,
             "system": system, "build_registry_sha256": build_sha,
             "refreeze_registry_sha256": registry_sha,
             "candidate_binding_eligible": True, "blockers": [],
             "fragment_identity": {"image_id": image_id}, "physical_identity": physical}
    value["receipt_sha256"] = refreeze.self_sha256(value, "receipt_sha256")
    runtimes[system] = emit(system + ".json", value)
output = directory / "patch.json"
patch = refreeze.assemble_identity_patch(
    project_root=project, registry_path=project / refreeze.REGISTRY_RELATIVE_PATH,
    native_receipt=native, worker_receipt=workers, runtime_receipts=runtimes, output=output)
assert refreeze.load_identity_patch(project_root=project, patch_path=output,
                                    require_candidate_eligible=True) == patch
preserved_stock = (
    hashlib.sha256((authority / "scripts/publication_image_build_v1.py").read_bytes()).hexdigest()
        == "7a8d6cf67de32515cf330073f3933b7af4216e552c5d606e8a17df500cf7938a"
    and hashlib.sha256(Path(refreeze.__file__).read_bytes()).hexdigest()
        == "38757bd592fed2c137325f0f4b320812145ac64a2a78550a85e549bf0a0cbb8a")
print(json.dumps({"patch": patch, "reader_verified": True,
                  "stock_read_verified": preserved_stock,
                  "authority_kind": "preserved-stock" if preserved_stock else "current-production",
                  "fixture_label": "artificial-physical-metadata-only",
                  "recovery_acceptance": False,
                  "source_paths": {"refreeze": refreeze.__file__}}, sort_keys=True))
'''

CHAIN_CHILD = r'''
import hashlib, json, sys, traceback
from pathlib import Path
package, project, patch = map(Path, sys.argv[1:4])
provenance = json.loads(Path(sys.argv[4]).read_bytes()) if len(sys.argv) > 4 else None
project_stems = ({Path(row["lexical_path"]).stem for row in provenance["files"]}
                 if provenance is not None else {path.stem for path in (package / "scripts").glob("*.py")})
sys.path.insert(0, str(package / "scripts"))
import publication_policy_qualification_fragment_validation_v2 as fragment
import publication_policy_qualification_fragment_validation_v2 as validation
assert fragment.DEFAULT_DEPENDENCIES is validation.DEFAULT_DEPENDENCIES
assert fragment.DEFAULT_DEPENDENCIES.load_identity_patch is validation._default_load_identity_patch
assert validation.FragmentAuthorityDependenciesV2.__dataclass_fields__["load_identity_patch"].default is validation._default_load_identity_patch
for forbidden in ("publication_image_build_v1.py", "materialize_runtime_build_context_v3.py"):
    assert not (package / "scripts" / forbidden).exists(), forbidden
def chain(error):
    if error is None: return None
    return {"type": type(error).__module__ + "." + type(error).__qualname__,
            "message": str(error), "cause": chain(error.__cause__),
            "context": chain(error.__context__), "suppress_context": error.__suppress_context__}
def loaded():
    result = {}
    for name, module in sorted(sys.modules.items()):
        file = getattr(module, "__file__", None)
        if file and Path(file).is_file() and (name.startswith("publication_") or name.startswith("checkpoint_") or Path(file).stem in project_stems):
            lexical = Path(file).absolute()
            path = lexical.resolve(strict=True)
            assert lexical.is_relative_to((package / "scripts").absolute()), str(lexical)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if provenance is not None:
                row = next(row for row in provenance["files"] if row["lexical_path"] == str(lexical))
                assert str(path) == row["resolved_path"] and digest == row["sha256"]
                if row["source_kind"] == "unchanged-owned-native-baseline":
                    assert lexical.is_symlink() and str(lexical.readlink()) == row["baseline_path"]
                else:
                    assert not lexical.is_symlink() and path == lexical
            else:
                assert path.is_relative_to((package / "scripts").resolve()), str(path)
            result[name] = {"path": str(lexical), "resolved_path": str(path), "sha256": digest}
    return result
try:
    value = fragment.DEFAULT_DEPENDENCIES.load_identity_patch(
        project_root=project, patch_path=patch, require_candidate_eligible=True)
except Exception as error:
    print(json.dumps({"outcome": "error", "error": chain(error),
                      "loaded_project_modules": loaded(), "project_search_roots": [str(package / "scripts")],
                      "unchanged_default_callback": True, "recovery_acceptance": False}, sort_keys=True))
    traceback.print_exc()
    raise SystemExit(2)
print(json.dumps({"outcome": "return", "value": value,
                  "loaded_project_modules": loaded(), "project_search_roots": [str(package / "scripts")],
                  "unchanged_default_callback": True, "recovery_acceptance": False}, sort_keys=True))
'''


def _reader_child(mode: str) -> str:
    return r'''
import hashlib, json, stat, sys
from pathlib import Path
from typing import Mapping
project, path = map(Path, sys.argv[1:3])
RECEIPT_KIND = "vast_publication_image_freeze_receipt_v1"
''' + (
        "exec(compile(" + repr(STOCK_READER_SOURCE) + ", '<sealed-stock-reader>', 'exec'))\n"
        if mode == "stock" else
        "sys.path.insert(0, str(project / 'scripts'))\n"
        "from publication_image_freeze_receipt_validation_v1 import "
        "load_publication_image_freeze_receipt, _canonical_json, _receipt_sha256\n"
    ) + r'''
def chain(error):
    if error is None: return None
    return {"type": type(error).__module__ + "." + type(error).__qualname__,
            "message": str(error), "cause": chain(error.__cause__),
            "context": chain(error.__context__), "suppress_context": error.__suppress_context__}
try:
    value = load_publication_image_freeze_receipt(path)
    result = {"outcome": "return", "value": value,
              "canonical_hex": _canonical_json(value).hex(),
              "receipt_sha256": _receipt_sha256(value)}
except Exception as error:
    result = {"outcome": "error", "error": chain(error)}
print(json.dumps(result, sort_keys=True))
'''


class PublicationImageFreezeReceiptValidationV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if hashlib.sha256(STOCK_READER_SOURCE.encode()).hexdigest() != STOCK_FUNCTION_SHA256:
            raise AssertionError("sealed original stock reader bytes drifted")
        cls.started = time.monotonic()
        cohort_pin = os.environ.get("VAST_PACKAGE_READER_OVERLAY_PIN")
        cls.overlay_pin = json.loads(Path(cohort_pin).read_bytes()) if cohort_pin else None
        cls.code_provenance = None
        cls.code_provenance_path = None
        cls.authority = Path(os.environ.get("VAST_PACKAGE_READER_STOCK", str(ROOT)))
        retained = os.environ.get("VAST_PACKAGE_READER_STAGE")
        reused = os.environ.get("VAST_PACKAGE_READER_REUSE_SOURCES")
        cls.temporary = None
        if retained:
            cls.directory = Path(retained)
        else:
            cls.temporary = tempfile.TemporaryDirectory(
                prefix="vast-package-reader-", dir="/var/tmp" if Path("/var/tmp").is_dir() else None)
            cls.directory = Path(cls.temporary.name)
        cls.controls = Path(os.environ.get("VAST_PACKAGE_READER_REPORTS", str(cls.directory / "reports")))
        assert not reused or cls.overlay_pin, "reused sources require retained-root pin"
        cls._guard_source_allocation(0)
        if retained:
            if reused:
                assert cls.directory.is_dir()
            else:
                cls.directory.mkdir(exist_ok=False)
        cls.project = cls.directory / "physical-project"
        if not reused:
            cls.project.mkdir()
        cls.package = cls.directory / "packaged-source"
        if not reused:
            cls.package.mkdir()
        cls.controls.mkdir(exist_ok=False)
        registry = json.loads((ROOT / "configs/publication_qualification_image_refreeze_v1.json").read_bytes())
        paths = {"configs/publication_image_build_v1.json", "configs/publication_qualification_image_refreeze_v1.json"}
        for row in registry["systems"]:
            paths.update((row["source_allowlist"], row["dependency_allowlist"], row["dockerfile"]))
            for field in ("source_allowlist", "dependency_allowlist"):
                paths.update((ROOT / row[field]).read_text(encoding="utf-8").splitlines())
        cls.sources = []
        if not reused:
            anticipated = 0
            for relative in paths:
                size = 0 if relative.endswith(".whl") else (ROOT / relative).stat().st_size
                anticipated += size
                if relative.startswith("scripts/") and relative.endswith(".py") and Path(relative).name != MATERIALIZER_NAME:
                    anticipated += size
            cls._guard_source_allocation(anticipated)
        if reused:
            cls.sources = json.loads(Path(reused).read_bytes())["sources"]
            for row in cls.sources:
                content = (cls.directory / row["tree"] / row["path"]).read_bytes()
                assert len(content) == row["bytes"] and hashlib.sha256(content).hexdigest() == row["sha256"]
        for relative in (() if reused else sorted(paths)):
            destination = cls.project / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            artificial = relative.endswith(".whl")
            content = b"" if artificial else (ROOT / relative).read_bytes()
            cls._write_staged_source(destination, content)
            cls.sources.append({"tree": "physical-project", "path": relative, "bytes": len(content),
                                "sha256": hashlib.sha256(content).hexdigest(),
                                "artificial_path_existence_input": artificial})
            if relative.startswith("scripts/") and relative.endswith(".py") and Path(relative).name != MATERIALIZER_NAME:
                packaged = cls.package / relative
                packaged.parent.mkdir(parents=True, exist_ok=True)
                cls._write_staged_source(packaged, content)
                cls.sources.append({"tree": "packaged-source", "path": relative,
                                    "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(),
                                    "artificial_path_existence_input": False})
        assert sum(row["bytes"] for row in cls.sources) <= 8 * 1024 * 1024
        assert not (cls.package / "scripts" / BUILDER_NAME).exists()
        assert not (cls.package / "scripts" / MATERIALIZER_NAME).exists()
        assert (cls.project / "scripts" / MATERIALIZER_NAME).is_file()
        if cls.overlay_pin:
            assert reused and retained
            baseline = cls.package
            view = cls.directory / cls.overlay_pin["view_name"]
            replacements = {row["path"]: row for row in cls.overlay_pin["source_files"]}
            assert view.name.startswith("green-code-view-") and view.name == cls.overlay_pin["view_name"]
            anticipated_view = sum(row["bytes"] for row in replacements.values()) + sum(
                len(os.fsencode(str((baseline / row["path"]).absolute()))) for row in cls.sources
                if row["tree"] == "packaged-source" and row["path"] not in replacements)
            cls._guard_source_allocation(anticipated_view)
            (view / "scripts").mkdir(parents=True, exist_ok=False)
            assert set(replacements) == {
                "scripts/publication_qualification_image_refreeze_v1.py",
                "scripts/publication_image_freeze_receipt_validation_v1.py"}
            file_rows = []
            for row in cls.sources:
                if row["tree"] != "packaged-source" or row["path"] in replacements:
                    continue
                target = baseline / row["path"]
                assert target.resolve(strict=True) == target.absolute() and target.stat().st_nlink == 1
                link = view / row["path"]
                cls._guard_source_allocation(len(os.fsencode(str(target.absolute()))))
                link.symlink_to(target.absolute())
                file_rows.append({"lexical_path": str(link.absolute()), "resolved_path": str(target.absolute()),
                                  "baseline_path": str(target.absolute()), "sha256": row["sha256"],
                                  "bytes": row["bytes"], "source_kind": "unchanged-owned-native-baseline"})
            for relative, row in replacements.items():
                source = Path(cls.overlay_pin["overlay_source_root"]) / relative
                content = source.read_bytes()
                assert len(content) == row["bytes"] and hashlib.sha256(content).hexdigest() == row["sha256"]
                path = view / relative
                cls._write_staged_source(path, content)
                file_rows.append({"lexical_path": str(path.absolute()), "resolved_path": str(path.absolute()),
                                  "sha256": row["sha256"], "bytes": row["bytes"],
                                  "source_kind": "new-pinned-overlay-source"})
            cls.package = view
            assert not os.path.lexists(view / "scripts" / BUILDER_NAME)
            assert not os.path.lexists(view / "scripts" / MATERIALIZER_NAME)
            cls.code_provenance = {"kind": "single-effective-code-root-provenance.v1",
                                   "effective_code_root": str(view / "scripts"), "files": file_rows,
                                   "baseline_code_root": str(baseline / "scripts"),
                                   "builder_and_materializer_absent": True,
                                   "host_rescue_or_loader_default_cache_override": False}
            cls.code_provenance_path = cls.controls / "green-code-view.source-provenance.original.v1.json"
            cls._verify_code_view()
            cls._record(cls.code_provenance_path.name, cls.code_provenance)
            view_bytes = sum(path.lstat().st_size for path in (view / "scripts").iterdir())
            assert sum(row["bytes"] for row in cls.sources) + view_bytes <= 8 * 1024 * 1024
        cls._record("staged-sources.original.v1.json", {
            "sources": cls.sources,
            "scripts_python_count": sum(row["tree"] == "physical-project" and row["path"].startswith("scripts/") and row["path"].endswith(".py") for row in cls.sources),
            "scripts_python_bytes": sum(row["bytes"] for row in cls.sources if row["tree"] == "physical-project" and row["path"].startswith("scripts/") and row["path"].endswith(".py")),
            "isolated_package_python_count": sum(row["tree"] == "packaged-source" for row in cls.sources),
            "isolated_package_python_bytes": sum(row["bytes"] for row in cls.sources if row["tree"] == "packaged-source"),
            "omitted_from_isolated_package": ["scripts/" + MATERIALIZER_NAME],
            "physical_project_materializer_is_data_outside_package_search_root": True,
            "reused_hash_verified_source_inputs": bool(reused),
            "effective_code_files": len(cls.code_provenance["files"]) if cls.code_provenance else None,
            "effective_code_provenance": str(cls.code_provenance_path) if cls.code_provenance_path else None,
            "stock_builder_absent": True, "actual_materializer_absent": True,
            "fixture_label": "artificial-physical-metadata-only",
            "dependency_wheel_source_build_image_acceptance": False,
            "recovery_acceptance": False})

    @classmethod
    def tearDownClass(cls) -> None:
        cls._check_caps()
        for row in cls.sources:
            content = (cls.directory / row["tree"] / row["path"]).read_bytes()
            assert len(content) == row["bytes"] and hashlib.sha256(content).hexdigest() == row["sha256"]
        cls._verify_code_view()
        cls._record("staged-sources.after.v1.json", {"source_bytes_unchanged": True, "recovery_acceptance": False})
        if cls.temporary is not None:
            cls.temporary.cleanup()

    @classmethod
    def _retained_source_bytes(cls) -> int:
        roots = [Path(path) for path in cls.overlay_pin["retained_native_roots"]] if cls.overlay_pin else [cls.directory]
        assert len(roots) == len(set(roots)) and cls.directory in roots
        total = 0
        for root in roots:
            if not root.exists():
                assert root == cls.directory and not os.environ.get("VAST_PACKAGE_READER_REUSE_SOURCES"), "retained source root missing"
                continue
            assert root.is_dir() and not root.is_symlink(), "retained source root changed"
            for subtree in root.iterdir():
                # "package" is the failed01 legacy source tree, never omitted.
                if subtree.name not in {"package", "physical-project", "packaged-source"} and not subtree.name.startswith("green-code-view-"):
                    continue
                for path in subtree.rglob("*"):
                    parts = path.relative_to(subtree).parts
                    if subtree.name == "physical-project" and parts[0] in {"metadata-cases", "reader-cases"}:
                        continue
                    if path.is_file() or path.is_symlink():
                        total += path.lstat().st_size
        return total

    @classmethod
    def _guard_source_allocation(cls, additional_bytes: int) -> None:
        assert isinstance(additional_bytes, int) and additional_bytes >= 0
        used = cls._retained_source_bytes()
        assert used + additional_bytes <= 8 * 1024 * 1024, (
            f"cumulative staged source cap exceeded: {used}+{additional_bytes}")
        cls._check_caps(additional_bytes=additional_bytes)

    @classmethod
    def _write_staged_source(cls, path: Path, content: bytes) -> None:
        cls._guard_source_allocation(len(content))
        with path.open("xb") as destination:
            destination.write(content)

    @classmethod
    def _check_caps(cls, *, additional_bytes: int = 0) -> None:
        assert time.monotonic() - cls.started <= 15 * 60, "cohort deadline exceeded"
        def size(root: Path, exclude: Path | None = None) -> int:
            return sum(path.lstat().st_size for path in root.rglob("*")
                       if (path.is_file() or path.is_symlink()) and (exclude is None or not path.is_relative_to(exclude)))
        report_root = Path(cls.overlay_pin["control_root"]) if cls.overlay_pin else cls.controls
        extras = cls.overlay_pin.get("additional_control_roots", []) if cls.overlay_pin else []
        report_roots = [report_root, *(Path(row["path"]) for row in extras)]
        assert all(not a.is_relative_to(b) and not b.is_relative_to(a)
                   for i, a in enumerate(report_roots) for b in report_roots[i + 1:])
        for row in extras:
            assert size(Path(row["path"])) <= row["max_bytes"], "external review allocation exceeded"
        native_roots = [Path(path) for path in cls.overlay_pin["retained_native_roots"]] if cls.overlay_pin else [cls.directory]
        assert len(native_roots) == len(set(native_roots))
        if cls.overlay_pin:
            assert cls.directory in native_roots
            assert all(path.parent == Path("/var/tmp") and path.name.startswith("vast-package-reader-bounded-01-") for path in native_roots)
        reports = sum(size(path) for path in report_roots)
        total = reports + sum(size(path, report_root) for path in native_roots) + Path(__file__).stat().st_size
        assert reports <= 4 * 1024 * 1024, "reports cap exceeded"
        assert total + additional_bytes <= 16 * 1024 * 1024, "cohort cap exceeded"

    @classmethod
    def _verify_code_view(cls) -> None:
        if cls.code_provenance is None:
            return
        for row in cls.code_provenance["files"]:
            path = Path(row["lexical_path"])
            assert str(path.resolve(strict=True)) == row["resolved_path"]
            content = path.read_bytes()
            assert len(content) == row["bytes"] and hashlib.sha256(content).hexdigest() == row["sha256"]
            if row["source_kind"] == "unchanged-owned-native-baseline":
                assert path.is_symlink() and str(path.readlink()) == row["baseline_path"]
                assert Path(row["baseline_path"]).stat().st_nlink == 1
            else:
                assert not path.is_symlink() and path.stat().st_nlink == 1

    @classmethod
    def _record(cls, name: str, value: object) -> None:
        path = cls.controls / name
        data = json.dumps(value, sort_keys=True, indent=2).encode() + b"\n"
        assert len(data) <= 1024 * 1024
        with path.open("xb") as output:
            output.write(data)

    def _invoke(self, name: str, program: str, *args: Path) -> tuple[subprocess.CompletedProcess[bytes], dict[str, object]]:
        self._check_caps()
        argv = [sys.executable, "-I", "-B", "-c", program, *(str(arg) for arg in args)]
        budget = min(60, 15 * 60 - (time.monotonic() - self.started))
        try:
            result = subprocess.run(
                argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=budget, check=False,
            )
        except subprocess.TimeoutExpired as error:
            self.assertLessEqual(len(error.stdout or b"") + len(error.stderr or b""), 1024 * 1024)
            for suffix, content in (("stdout", error.stdout or b""), ("stderr", error.stderr or b"")):
                with (self.controls / f"{name}.{suffix}.original").open("xb") as output:
                    output.write(content)
            self._record(f"{name}.execution.original.v1.json", {
                "argv": argv, "original_returncode": None, "timed_out": True,
                "child_timeout_seconds": budget, "recovery_acceptance": False})
            raise
        self.assertLessEqual(len(result.stdout) + len(result.stderr), 1024 * 1024)
        for suffix, content in (("stdout", result.stdout), ("stderr", result.stderr)):
            with (self.controls / f"{name}.{suffix}.original").open("xb") as output:
                output.write(content)
        self._record(f"{name}.execution.original.v1.json", {
            "argv": result.args, "original_returncode": result.returncode,
            "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
            "child_timeout_seconds": budget, "fixture_label": "artificial-physical-metadata-only",
            "recovery_acceptance": False})
        self._check_caps()
        return result, json.loads(result.stdout) if result.stdout else {}

    def _fixture(self, name: str) -> tuple[Path, dict[str, object]]:
        suffix = os.environ.get("VAST_PACKAGE_READER_CASE_SUFFIX", "")
        assert not suffix or (suffix.startswith("-") and suffix[1:].isalnum())
        destination = self.project / "metadata-cases" / (name + suffix)
        destination.parent.mkdir(exist_ok=True)
        result, report = self._invoke("prepare-" + name, PREPARE_CHILD, self.authority, self.project, destination)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertIs(report["reader_verified"], True)
        stock = (
            hashlib.sha256((self.authority / "scripts" / BUILDER_NAME).read_bytes()).hexdigest() == STOCK_BUILDER_SHA256
            and hashlib.sha256((self.authority / "scripts/publication_qualification_image_refreeze_v1.py").read_bytes()).hexdigest() == STOCK_REFREEZE_SHA256)
        self.assertIs(report["stock_read_verified"], stock)
        self.assertEqual(report["authority_kind"], "preserved-stock" if stock else "current-production")
        self.assertLessEqual(sum(p.stat().st_size for p in destination.rglob("*") if p.is_file()), 1024 * 1024)
        return destination / "patch.json", report["patch"]

    def test_retained_source_counter_covers_all_roots_and_link_bytes(self) -> None:
        # Tiny accounting metadata only: these files are never imported as sources.
        self._check_caps(additional_bytes=1024)
        fixture = self.controls / "source-counter-contract"
        old, current = fixture / "retained-a", fixture / "retained-b"
        rows = [
            (old / "package/old.py", b"old"),
            (current / "physical-project/input.py", b"input"),
            (current / "packaged-source/shared.py", b"shared!"),
            (current / "green-code-view-contract/scripts/new.py", b"view"),
            (current / "physical-project/metadata-cases/case.json", b"excluded-case"),
            (current / "physical-project/reader-cases/case.json", b"excluded-reader"),
        ]
        for path, data in rows:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as output:
                output.write(data)
        link = current / "green-code-view-contract/scripts/shared.py"
        link.symlink_to((current / "packaged-source/shared.py").absolute())
        expected = 19 + link.lstat().st_size
        with mock.patch.object(type(self), "directory", current), mock.patch.object(
                type(self), "overlay_pin", {"retained_native_roots": [str(old), str(current)]}):
            self.assertEqual(self._retained_source_bytes(), expected)
            missing = fixture / "declared-missing"
            type(self).overlay_pin["retained_native_roots"].append(str(missing))
            with self.assertRaisesRegex(AssertionError, "retained source root missing"):
                self._retained_source_bytes()
        self.assertLessEqual(sum(path.lstat().st_size for path in fixture.rglob("*")
                                 if path.is_file() or path.is_symlink()), 1024)
        self._check_caps()

    def test_cumulative_source_guard_refuses_before_a_new_write(self) -> None:
        destination = self.project / "forbidden-staging-write.py"
        with mock.patch.object(type(self), "_retained_source_bytes", return_value=12_677_599):
            with self.assertRaisesRegex(AssertionError, "cumulative staged source cap exceeded"):
                self._write_staged_source(destination, b"x")
        self.assertFalse(destination.exists())

    def test_default_packaged_identity_patch_loads_without_host_builder(self) -> None:
        patch_path, expected = self._fixture("default-chain")
        provenance = (self.code_provenance_path,) if self.code_provenance_path else ()
        result, report = self._invoke("default-chain", CHAIN_CHILD, self.package, self.project, patch_path, *provenance)
        self.assertEqual(result.returncode, 0, json.dumps(report, sort_keys=True))
        self.assertEqual(report["outcome"], "return")
        self.assertEqual(report["value"], expected)
        self.assertIs(report["unchanged_default_callback"], True)

    def test_stock_and_leaf_receipt_cases_have_identical_results_and_errors(self) -> None:
        case_root = self.project / "reader-cases"
        case_root.mkdir()
        valid = _signed({"artifact_kind": RECEIPT_KIND, "schema_version": 1, "images": []})
        values = {
            "canonical": valid,
            "noncanonical": valid,
            "unicode": _signed({**valid, "note": "\u0442\u0435\u0441\u0442/\u00e9/\U0001f642"}),
            "schema-bool-stock-equality": _signed({**valid, "schema_version": True}),
            "schema-float-stock-equality": _signed({**valid, "schema_version": 1.0}),
            "images-elements-stock-quirk": _signed({**valid, "images": [None, True, "x", 1, {}]}),
            "foreign-kind": _signed({**valid, "artifact_kind": "foreign"}),
            "foreign-schema": _signed({**valid, "schema_version": 2}),
            "missing-schema": _signed({key: value for key, value in valid.items() if key != "schema_version"}),
            "schema-string-refusal": _signed({**valid, "schema_version": "1"}),
            "missing-kind": _signed({key: value for key, value in valid.items() if key != "artifact_kind"}),
            "missing-self-hash": {key: value for key, value in valid.items() if key != "receipt_sha256"},
            "wrong-self-hash": {**valid, "receipt_sha256": "0" * 64},
            "nonstring-self-hash": {**valid, "receipt_sha256": True},
            "wrong-images-type": _signed({**valid, "images": {}}),
            "missing-images": _signed({key: value for key, value in valid.items() if key != "images"}),
            "root-list": [],
            "nan-canonical-refusal": {**valid, "note": float("nan"), "receipt_sha256": "0" * 64},
        }
        cases = {}
        for name, value in values.items():
            path = case_root / (name + ".json")
            if name == "canonical":
                content = _canonical(value) + b"\n"
            elif name == "noncanonical":
                content = json.dumps(value, ensure_ascii=False, indent=2).encode()
            else:
                content = json.dumps(value, ensure_ascii=True).encode()
            path.write_bytes(content)
            cases[name] = path
        for name, content in (("malformed-json", b"{"), ("invalid-encoding", b"\xff")):
            path = case_root / (name + ".json")
            path.write_bytes(content)
            cases[name] = path
        cases["missing-file"] = case_root / "absent.json"
        directory = case_root / "directory"
        directory.mkdir()
        cases["directory"] = directory
        target = case_root / "link-target.json"
        target.write_bytes(_canonical(valid))
        symbolic = case_root / "symlink.json"
        symbolic.symlink_to(target)
        cases["symlink"] = symbolic
        hard_target = case_root / "hard-target.json"
        hard_target.write_bytes(_canonical(valid))
        hard = case_root / "hardlink.json"
        os.link(hard_target, hard)
        cases["hardlink"] = hard
        self.assertLessEqual(sum(p.stat().st_size for p in case_root.rglob("*") if p.is_file()), 1024 * 1024)
        for name, path in cases.items():
            with self.subTest(case=name):
                stock_result, stock = self._invoke(name + "-stock", _reader_child("stock"), self.package, path)
                leaf_result, leaf = self._invoke(name + "-leaf", _reader_child("leaf"), self.package, path)
                self.assertEqual(stock_result.returncode, 0, stock_result.stderr.decode(errors="replace"))
                self.assertEqual(leaf_result.returncode, 0, leaf_result.stderr.decode(errors="replace"))
                self.assertEqual(leaf, stock)
                self.assertEqual(stock["outcome"], "return" if name in {
                    "canonical", "noncanonical", "unicode", "schema-bool-stock-equality",
                    "schema-float-stock-equality", "images-elements-stock-quirk"} else "error")

    def test_default_chain_keeps_outer_descriptor_and_physical_refusals(self) -> None:
        for name in ("descriptor", "receipt-symlink", "receipt-hardlink"):
            with self.subTest(case=name):
                patch_path, patch = self._fixture("outer-" + name)
                relative = patch["receipts"]["native_probe"]["path"]
                receipt = self.project / relative
                if name == "descriptor":
                    receipt.write_bytes(receipt.read_bytes() + b" ")
                elif name == "receipt-symlink":
                    target = receipt.with_name("native-target.json")
                    receipt.rename(target)
                    receipt.symlink_to(target)
                else:
                    os.link(receipt, receipt.with_name("native-hardlink.json"))
                provenance = (self.code_provenance_path,) if self.code_provenance_path else ()
                result, report = self._invoke("outer-" + name, CHAIN_CHILD, self.package, self.project, patch_path, *provenance)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(report["outcome"], "error")
                message = report["error"]["message"]
                self.assertIn("descriptor drifted" if name == "descriptor" else "unaliased physical file", message)
                self.assertEqual(json.loads(patch_path.read_bytes()), patch)

    def test_host_public_reader_reexports_the_same_leaf_callable(self) -> None:
        program = r'''
import importlib.util, json, sys
from pathlib import Path
source_scripts = Path(sys.argv[1]) / "scripts"
sys.path.insert(0, str(source_scripts))
import publication_image_build_v1 as builder
import publication_image_freeze_receipt_validation_v1 as leaf
spec = importlib.util.spec_from_file_location("host_builder_fixed_file_fixture", source_scripts / "publication_image_build_v1.py")
assert spec is not None and spec.loader is not None
alias = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alias)
import publication_policy_qualification_fragments_from_authority_v2 as fragment
import publication_policy_qualification_fragment_validation_v2 as validation
assert builder.load_publication_image_freeze_receipt is leaf.load_publication_image_freeze_receipt
assert alias.load_publication_image_freeze_receipt is leaf.load_publication_image_freeze_receipt
assert fragment.DEFAULT_DEPENDENCIES is validation.DEFAULT_DEPENDENCIES
assert fragment.DEFAULT_DEPENDENCIES.load_identity_patch is validation._default_load_identity_patch
print(json.dumps({"public_reader_shared": True, "default_dependencies_shared": True,
                  "fixed_file_loader_alias_shared": True, "host_source_bootstrap": str(source_scripts),
                  "recovery_acceptance": False}))
'''
        result, report = self._invoke("host-shared-identity", program, ROOT)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertIs(report["public_reader_shared"], True)
        self.assertIs(report["fixed_file_loader_alias_shared"], True)


if __name__ == "__main__":
    unittest.main()
