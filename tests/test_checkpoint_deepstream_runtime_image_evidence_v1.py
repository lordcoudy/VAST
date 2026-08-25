from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import checkpoint_deepstream_publication_launcher_v3 as launcher  # noqa: E402


EVIDENCE = (
    ROOT
    / "artifacts/deepstream_publication_v3/runtime_image_evidence.v1.json"
)
FRAGMENT = (
    ROOT
    / "artifacts/deepstream_publication_v3/qualification/qualification_fragment.json"
)
IMAGE_ID = (
    "sha256:570d22005b3c2d43c0c6235db02efbccc52638e19a1daf0b08a82bf4013a046d"
)
SOURCE_CLOSURE_SHA256 = (
    "a0e5c4e06127ea35d642e97da97052582d811695cbeba84b3d817839554bb493"
)
RUNTIME_ENTRYPOINT = "/usr/local/bin/vast_deepstream_publication_runtime_v3"
DEPENDENCY_CLOSURE_SHA256 = (
    "90757e66da682415d78f3c78e21ea2a2c6f76db6611fef2587b7606ccb4bca80"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256sum_closure(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    relative_paths = sorted(
        (path.relative_to(ROOT).as_posix(), path)
        for path in paths
        if path.is_file() and not path.is_symlink()
    )
    for relative, path in relative_paths:
        digest.update(f"{_sha256(path)}  {relative}\n".encode("utf-8"))
    return digest.hexdigest()


class DeepStreamRuntimeImageEvidenceV1Tests(unittest.TestCase):
    def test_exact_materialized_image_evidence_and_qualification_fragment(self) -> None:
        evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(
            set(evidence),
            {
                "artifact_kind",
                "blockers",
                "build",
                "dependency_closure",
                "image_inspect",
                "native_dependency_resolution",
                "probe_results",
                "publication_ready",
                "runtime_owned_executable_allowlist",
                "schema_version",
                "source_closure",
                "system",
            },
        )
        self.assertEqual(
            evidence["artifact_kind"],
            "vast_deepstream_publication_runtime_image_evidence_v1",
        )
        self.assertEqual(evidence["schema_version"], 1)
        self.assertEqual(evidence["system"], "deepstream")
        self.assertIs(evidence["publication_ready"], False)
        self.assertEqual(evidence["blockers"], list(launcher.MISSING_RUNTIME_PINS))
        self.assertIs(launcher.PUBLICATION_READY, False)

        build = evidence["build"]
        self.assertEqual(build["a"]["image_id"], IMAGE_ID)
        self.assertEqual(build["b"]["image_id"], IMAGE_ID)
        self.assertIs(build["deterministic_exact_image_id"], True)
        self.assertEqual(build["cache_mode"], "no-cache")
        self.assertEqual(build["network_mode"], "none")
        self.assertIs(build["pull"], False)
        self.assertIs(build["provenance"], False)

        source_paths = [
            *SCRIPTS.glob("*.py"),
            *(ROOT / "deploy/native_gst_probe").rglob("*"),
            *(ROOT / "deploy/deepstream/checkpoint").rglob("*"),
            ROOT / "CMakeLists.txt",
        ]
        self.assertEqual(_sha256sum_closure(source_paths), SOURCE_CLOSURE_SHA256)
        self.assertEqual(
            evidence["source_closure"]["sha256"], SOURCE_CLOSURE_SHA256
        )

        dependency_paths = [
            ROOT / row["path"] for row in evidence["dependency_closure"]["files"]
        ]
        self.assertEqual(
            _sha256sum_closure(dependency_paths), DEPENDENCY_CLOSURE_SHA256
        )
        self.assertEqual(
            evidence["dependency_closure"]["sha256"],
            DEPENDENCY_CLOSURE_SHA256,
        )
        for row, path in zip(
            evidence["dependency_closure"]["files"], dependency_paths, strict=True
        ):
            self.assertEqual(row["size"], path.stat().st_size)
            self.assertEqual(row["sha256"], _sha256(path))

        inspect = evidence["image_inspect"]
        self.assertEqual(inspect["image_id"], IMAGE_ID)
        self.assertEqual(inspect["manifest_descriptor_digest"], IMAGE_ID)
        self.assertEqual(
            inspect["repository_digest"],
            "vast/deepstream-publication-runtime-v3@" + IMAGE_ID,
        )
        self.assertEqual(inspect["entrypoint"], [RUNTIME_ENTRYPOINT])
        self.assertEqual(inspect["labels"]["org.vast.publication-ready"], "false")
        self.assertEqual(
            inspect["labels"]["org.vast.runtime-source-sha256"],
            SOURCE_CLOSURE_SHA256,
        )
        self.assertEqual(inspect["rootfs_layer_count"], 56)

        allowlist = evidence["runtime_owned_executable_allowlist"]
        entries = allowlist["entries"]
        self.assertEqual(len(entries), 4)
        self.assertEqual(len({row["path"] for row in entries}), 4)
        closure = hashlib.sha256()
        for row in sorted(entries, key=lambda value: value["path"]):
            closure.update(
                f"{row['sha256']}  {row['path']}\n".encode("utf-8")
            )
        self.assertEqual(
            closure.hexdigest(),
            "e2cc61a163d7859c2ae7cbaf870ed56b6499547fded57cfbfa96406d56676184",
        )
        self.assertEqual(allowlist["sha256"], closure.hexdigest())
        self.assertEqual(
            evidence["native_dependency_resolution"]["missing_libraries"], []
        )
        self.assertIs(
            evidence["native_dependency_resolution"]["all_resolved"], True
        )

        for codec in ("h264", "h265"):
            probe = evidence["probe_results"]["nvdec_one_buffer"][codec]
            media = ROOT / probe["path"]
            self.assertEqual(probe["exit_code"], 0)
            self.assertEqual(probe["size"], media.stat().st_size)
            self.assertEqual(probe["sha256"], _sha256(media))

        fragment = json.loads(FRAGMENT.read_text(encoding="utf-8"))
        self.assertEqual(fragment["pilots"], [])
        self.assertEqual(len(fragment["policy_bindings"]), 8)
        self.assertEqual(len(fragment["resource_bindings"]), 2)
        self.assertEqual(
            {
                row["runtime_identity"]["device_api"]
                for row in fragment["policy_bindings"]
                if row["resource"] == "cpu"
            },
            {"CPU"},
        )
        self.assertEqual(
            {
                row["runtime_identity"]["analytics_device_api"]
                for row in fragment["resource_bindings"]
                if row["resource"] == "cpu"
            },
            {"HOST_CPU"},
        )


if __name__ == "__main__":
    unittest.main()
