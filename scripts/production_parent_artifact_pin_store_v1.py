#!/usr/bin/env python3
"""Durable parent-owned resume pins for one production ABI-v3 arm.

The transaction child owns only ``output_dir``.  This store persists the
parent's result/receipt observations in a sibling namespace before the
transaction advances to its next commit.  Every path component is traversed
without following links/reparse points and the namespace remains under held
physical-root custody for the lifetime of the store.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


SCHEMA_VERSION = 1
ARTIFACT_KIND = "vast_production_parent_artifact_pin_v1"
PIN_DIRECTORY_NAME = ".production-parent-artifact-pins-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_STATE_FILE_NAMES = {
    "result": "result.pin.v1.json",
    "receipt_intent": "receipt-intent.pin.v1.json",
    "committed": "committed.pin.v1.json",
}
_STATE_ARTIFACT_NAMES = {
    "result": "backend_publication_launcher_result_v3.json",
    "receipt_intent": "backend_publication_output_receipt_v3.json",
    "committed": "backend_publication_output_receipt_v3.json",
}


class ProductionParentArtifactPinStoreV1Error(RuntimeError):
    pass


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as error:
        raise ProductionParentArtifactPinStoreV1Error(
            f"parent artifact pin is not canonical JSON: {error}"
        ) from error


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _absolute_descendant(root: Path, value: Path, *, label: str) -> Path:
    """Normalize lexically without resolving attacker-controlled components."""

    candidate = Path(os.path.abspath(os.fspath(value)))
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        raise ProductionParentArtifactPinStoreV1Error(
            f"{label} escaped project_root"
        ) from None
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ProductionParentArtifactPinStoreV1Error(
            f"{label} must be a canonical project descendant"
        )
    return root.joinpath(*relative.parts)


def _validate_artifact_pin(value: Any, *, expected_state: str) -> dict[str, Any]:
    if (
        expected_state not in _STATE_FILE_NAMES
        or type(value) is not dict
        or set(value) != {"state", "path", "size_bytes", "sha256"}
        or value.get("state") != expected_state
        or value.get("path") != _STATE_ARTIFACT_NAMES[expected_state]
        or type(value.get("size_bytes")) is not int
        or value["size_bytes"] < 1
        or _SHA256_RE.fullmatch(str(value.get("sha256", ""))) is None
    ):
        raise ProductionParentArtifactPinStoreV1Error(
            "durable parent artifact pin descriptor drifted"
        )
    return copy.deepcopy(value)


class ProductionParentArtifactPinStoreV1:
    def __init__(
        self,
        *,
        project_root: Path,
        output_dir: Path,
        arm_contract_file_sha256: str,
        execution_binding: Mapping[str, Any],
        after_physical_commit_step: Callable[[str, Path], None] | None = None,
    ) -> None:
        supplied_root = Path(os.path.abspath(os.fspath(project_root)))
        self._custody: PhysicalRootCustodyV1 | None = None
        self._pin_custody: PhysicalRootCustodyV1 | None = None
        self._mutation_watch: Any | None = None
        self._closed = False
        try:
            self._custody = PhysicalRootCustodyV1.open(
                supplied_root,
                label="parent artifact pin project_root",
            )
            self.project_root = self._custody.root
            self.output_dir = _absolute_descendant(
                self.project_root,
                Path(output_dir),
                label="production arm output",
            )
            if self.output_dir.parent == self.project_root:
                raise ProductionParentArtifactPinStoreV1Error(
                    "production arm output requires a dedicated parent"
                )
            if not os.path.lexists(self.output_dir):
                raise ProductionParentArtifactPinStoreV1Error(
                    "production arm output is unavailable"
                )
            # ``ensure_directory`` is a no-follow/openat traversal on Linux and
            # rejects every Windows reparse component in its fallback.
            self._custody.ensure_directory(
                self.output_dir,
                label="production arm output custody",
            )
            if _SHA256_RE.fullmatch(str(arm_contract_file_sha256)) is None:
                raise ProductionParentArtifactPinStoreV1Error(
                    "arm contract file SHA-256 is invalid"
                )
            if type(execution_binding) is not dict:
                raise ProductionParentArtifactPinStoreV1Error(
                    "execution binding must be an exact object"
                )
            self.arm_contract_file_sha256 = str(arm_contract_file_sha256)
            self.execution_binding_sha256 = _sha256(dict(execution_binding))
            self._after_physical_commit_step = after_physical_commit_step
            self.output_relative_path = self.output_dir.relative_to(
                self.project_root
            ).as_posix()
            key = hashlib.sha256(
                self.output_relative_path.encode("utf-8")
            ).hexdigest()
            self.pin_root = _absolute_descendant(
                self.project_root,
                self.output_dir.parent / PIN_DIRECTORY_NAME / key,
                label="parent artifact pin root",
            )
            if self.pin_root == self.output_dir or self.pin_root.is_relative_to(
                self.output_dir
            ):
                raise ProductionParentArtifactPinStoreV1Error(
                    "parent artifact pin root is inside child-controlled output"
                )
            self._custody.ensure_directory(
                self.pin_root,
                label="parent artifact pin namespace custody",
            )
            # Re-check the physical result after creation.  A symlink/reparse
            # component cannot be normalized into a different trusted path.
            if self.pin_root.resolve(strict=True) != self.pin_root:
                raise ProductionParentArtifactPinStoreV1Error(
                    "parent artifact pin root is not one physical directory"
                )
            # Atomic staging must live below a writable, parent-controlled root.
            # The publication project root can legitimately be ``/`` (the
            # production transaction uses absolute executable/source pins), so
            # staging beneath the project root itself would require root access.
            # Pin a second custody at the dedicated pin namespace parent; its
            # staging directory is a sibling of the per-arm pin directory and
            # therefore never pollutes the strict per-arm inventory.
            self._pin_custody = PhysicalRootCustodyV1.open(
                self.pin_root.parent,
                label="parent artifact atomic pin namespace",
            )
            if self._pin_custody.root != self.pin_root.parent:
                raise ProductionParentArtifactPinStoreV1Error(
                    "parent artifact atomic pin namespace drifted"
                )
            self._start_mutation_watch()
        except PublicationPhysicalIoV1Error as error:
            self._close_unchecked()
            raise ProductionParentArtifactPinStoreV1Error(
                "parent artifact pin physical directory custody failed"
            ) from error
        except BaseException:
            self._close_unchecked()
            raise

    def _require_open(self) -> PhysicalRootCustodyV1:
        if self._closed or self._custody is None or self._pin_custody is None:
            raise ProductionParentArtifactPinStoreV1Error(
                "parent artifact pin store is closed"
            )
        return self._custody

    def _require_pin_custody(self) -> PhysicalRootCustodyV1:
        self._require_open()
        assert self._pin_custody is not None
        return self._pin_custody

    def _watch_probe(self) -> Path:
        return self.pin_root / ".parent-pin-namespace-watch-probe"

    def _start_mutation_watch(self) -> None:
        custody = self._require_open()
        try:
            self._mutation_watch = custody.begin_read_namespace_mutation_watch(
                [self._watch_probe()],
                label="parent artifact pin namespace",
            )
        except PublicationPhysicalIoV1Error as error:
            raise ProductionParentArtifactPinStoreV1Error(
                "parent artifact pin mutation watch failed"
            ) from error

    def _begin_operation(self) -> PhysicalRootCustodyV1:
        custody = self._require_open()
        pin_custody = self._require_pin_custody()
        token = self._mutation_watch
        self._mutation_watch = None
        try:
            custody.verify_pinned_directory_mutation_watch(
                token,
                label="parent artifact pin namespace",
            )
            custody.verify()
            # Re-traverse both trusted branches on every operation.  Directory
            # pins retained by PhysicalRootCustody reject permanent rebinds.
            custody.ensure_directory(
                self.output_dir,
                label="production arm output custody",
            )
            custody.ensure_directory(
                self.pin_root,
                label="parent artifact pin namespace custody",
            )
            pin_custody.verify()
            pin_custody.ensure_directory(
                self.pin_root,
                label="parent artifact atomic pin namespace custody",
            )
            return custody
        except PublicationPhysicalIoV1Error as error:
            raise ProductionParentArtifactPinStoreV1Error(
                "parent artifact pin directory custody changed"
            ) from error

    def _finish_operation(self) -> None:
        self._start_mutation_watch()

    def _path(self, state: str) -> Path:
        try:
            name = _STATE_FILE_NAMES[state]
        except KeyError:
            raise ProductionParentArtifactPinStoreV1Error(
                "parent artifact pin state is invalid"
            ) from None
        return self.pin_root / name

    def _envelope(self, pin: Mapping[str, Any], *, state: str) -> dict[str, Any]:
        normalized = _validate_artifact_pin(pin, expected_state=state)
        unsigned = {
            "schema_version": SCHEMA_VERSION,
            "artifact_kind": ARTIFACT_KIND,
            "status": "durable_parent_observation",
            "state": state,
            "output_relative_path": self.output_relative_path,
            "arm_contract_file_sha256": self.arm_contract_file_sha256,
            "execution_binding_sha256": self.execution_binding_sha256,
            "artifact_pin": normalized,
        }
        return {**unsigned, "pin_sha256": _sha256(unsigned)}

    def _read_optional_with_custody(
        self,
        custody: PhysicalRootCustodyV1,
        state: str,
        *,
        names: set[str] | None = None,
    ) -> bytes | None:
        path = self._path(state)
        observed_names = (
            set(
                custody.list_directory_names(
                    self.pin_root,
                    label="parent artifact pin namespace inventory",
                )
            )
            if names is None
            else names
        )
        if path.name not in observed_names:
            return None
        try:
            _descriptor, payload = custody.read_descriptor(
                path,
                label=f"parent artifact {state} pin",
                maximum=64 * 1024,
                capture=True,
            )
            return payload
        except PublicationPhysicalIoV1Error as error:
            raise ProductionParentArtifactPinStoreV1Error(
                f"parent artifact {state} pin is unsafe or unreadable"
            ) from error

    def __call__(self, pin: dict[str, Any]) -> None:
        state = str(pin.get("state", "")) if type(pin) is dict else ""
        envelope = self._envelope(pin, state=state)
        path = self._path(state)
        payload = _canonical_json(envelope) + b"\n"
        custody = self._begin_operation()
        try:
            names = set(
                custody.list_directory_names(
                    self.pin_root,
                    label="parent artifact pin namespace inventory",
                )
            )
            allowed = set(_STATE_FILE_NAMES.values())
            if not names <= allowed:
                raise ProductionParentArtifactPinStoreV1Error(
                    "parent artifact pin namespace contains unexpected entries"
                )
            if state in {"receipt_intent", "committed"}:
                result = self._load_with_custody(
                    custody,
                    "result",
                    names=names,
                )
                if result is None:
                    raise ProductionParentArtifactPinStoreV1Error(
                        f"{state} parent artifact pin lacks its result predecessor"
                    )
            if state == "committed":
                intent = self._load_with_custody(
                    custody,
                    "receipt_intent",
                    names=names,
                )
                if intent is None:
                    raise ProductionParentArtifactPinStoreV1Error(
                        "committed parent artifact pin lacks its receipt intent"
                    )
                if intent != {
                    "state": "receipt_intent",
                    "path": envelope["artifact_pin"]["path"],
                    "size_bytes": envelope["artifact_pin"]["size_bytes"],
                    "sha256": envelope["artifact_pin"]["sha256"],
                }:
                    raise ProductionParentArtifactPinStoreV1Error(
                        "committed parent artifact pin differs from receipt intent"
                    )
            existing = self._read_optional_with_custody(
                custody,
                state,
                names=names,
            )
            if existing is not None:
                if existing != payload:
                    raise ProductionParentArtifactPinStoreV1Error(
                        "parent artifact pin collision"
                    )
            expected = {
                "path": path.relative_to(self.project_root).as_posix(),
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            pin_custody = self._require_pin_custody()
            atomic_expected = {
                **expected,
                "path": path.relative_to(pin_custody.root).as_posix(),
            }

            def physical_step(step: str) -> None:
                if self._after_physical_commit_step is not None:
                    self._after_physical_commit_step(step, path)

            try:
                descriptor, identity, disposition = (
                    pin_custody.commit_or_adopt_exact_identity(
                        atomic_expected["path"],
                        payload,
                        label=f"parent artifact {state} pin",
                        mode=0o400,
                        create_parents=False,
                        after_publish_step=physical_step,
                    )
                )
            except PublicationPhysicalIoV1Error as error:
                raise ProductionParentArtifactPinStoreV1Error(
                    "parent artifact pin atomic commit/adoption failed"
                ) from error
            if descriptor != atomic_expected or disposition not in {"published", "adopted"}:
                raise ProductionParentArtifactPinStoreV1Error(
                    "parent artifact pin atomic commit result drifted"
                )
            observed, cold_payload, cold_identity = pin_custody.read_descriptor_identity(
                atomic_expected["path"],
                label=f"committed parent artifact {state} pin",
                maximum=len(payload),
                capture=True,
            )
            observed_mode, stat_identity = pin_custody.stat_regular_identity(
                atomic_expected["path"],
                label=f"committed parent artifact {state} pin mode",
            )
            if (
                observed != atomic_expected
                or cold_payload != payload
                or cold_identity != identity
                or stat_identity != identity
                or observed_mode != 0o400
            ):
                raise ProductionParentArtifactPinStoreV1Error(
                    "parent artifact pin durable identity drifted"
                )
            pin_custody.verify()
            custody.verify()
        finally:
            self._finish_operation()

    def _load_with_custody(
        self,
        custody: PhysicalRootCustodyV1,
        state: str,
        *,
        names: set[str] | None = None,
    ) -> dict[str, Any] | None:
        raw = self._read_optional_with_custody(
            custody,
            state,
            names=names,
        )
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ProductionParentArtifactPinStoreV1Error(
                f"parent artifact pin is invalid: {error}"
            ) from error
        if type(value) is not dict or set(value) != {
            "schema_version",
            "artifact_kind",
            "status",
            "state",
            "output_relative_path",
            "arm_contract_file_sha256",
            "execution_binding_sha256",
            "artifact_pin",
            "pin_sha256",
        }:
            raise ProductionParentArtifactPinStoreV1Error(
                "parent artifact pin envelope fields drifted"
            )
        unsigned = {key: item for key, item in value.items() if key != "pin_sha256"}
        expected = self._envelope(value.get("artifact_pin"), state=state)
        if (
            raw != _canonical_json(value) + b"\n"
            or value != expected
            or value.get("pin_sha256") != _sha256(unsigned)
        ):
            raise ProductionParentArtifactPinStoreV1Error(
                "parent artifact pin identity drifted"
            )
        return copy.deepcopy(value["artifact_pin"])

    def _namespace_names(self, custody: PhysicalRootCustodyV1) -> set[str]:
        try:
            return set(
                custody.list_directory_names(
                    self.pin_root,
                    label="parent artifact pin namespace inventory",
                )
            )
        except PublicationPhysicalIoV1Error as error:
            raise ProductionParentArtifactPinStoreV1Error(
                "parent artifact pin namespace inventory failed"
            ) from error

    def load_expected_pin(self) -> dict[str, Any] | None:
        custody = self._begin_operation()
        try:
            names = self._namespace_names(custody)
            allowed = set(_STATE_FILE_NAMES.values())
            if not names <= allowed:
                raise ProductionParentArtifactPinStoreV1Error(
                    "parent artifact pin namespace contains unexpected entries"
                )
            result = self._load_with_custody(
                custody,
                "result",
                names=names,
            )
            intent = self._load_with_custody(
                custody,
                "receipt_intent",
                names=names,
            )
            committed = self._load_with_custody(
                custody,
                "committed",
                names=names,
            )
            if intent is not None and result is None:
                raise ProductionParentArtifactPinStoreV1Error(
                    "receipt-intent parent pin lacks its result predecessor"
                )
            if committed is not None and (result is None or intent is None):
                raise ProductionParentArtifactPinStoreV1Error(
                    "committed parent artifact pin lacks its WAL predecessors"
                )
            if committed is not None and intent != {
                "state": "receipt_intent",
                "path": committed["path"],
                "size_bytes": committed["size_bytes"],
                "sha256": committed["sha256"],
            }:
                raise ProductionParentArtifactPinStoreV1Error(
                    "committed parent artifact pin differs from receipt intent"
                )
            return committed if committed is not None else intent or result
        finally:
            self._finish_operation()

    def _close_unchecked(self) -> None:
        token = getattr(self, "_mutation_watch", None)
        self._mutation_watch = None
        if token is not None:
            try:
                token.close()
            except Exception:
                pass
        custody = getattr(self, "_custody", None)
        pin_custody = getattr(self, "_pin_custody", None)
        self._custody = None
        self._pin_custody = None
        self._closed = True
        if pin_custody is not None:
            try:
                pin_custody.close()
            except Exception:
                pass
        if custody is not None:
            try:
                custody.close()
            except Exception:
                pass

    def close(self) -> None:
        if self._closed:
            return
        custody = self._require_open()
        token = self._mutation_watch
        self._mutation_watch = None
        try:
            custody.verify_pinned_directory_mutation_watch(
                token,
                label="parent artifact pin namespace",
            )
            custody.verify()
        except PublicationPhysicalIoV1Error as error:
            raise ProductionParentArtifactPinStoreV1Error(
                "parent artifact pin directory custody changed before close"
            ) from error
        finally:
            self._close_unchecked()

    def __enter__(self) -> "ProductionParentArtifactPinStoreV1":
        self._require_open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        self._close_unchecked()


__all__ = [
    "ARTIFACT_KIND",
    "PIN_DIRECTORY_NAME",
    "ProductionParentArtifactPinStoreV1",
    "ProductionParentArtifactPinStoreV1Error",
    "SCHEMA_VERSION",
]
