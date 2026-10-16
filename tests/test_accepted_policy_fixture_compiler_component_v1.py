"""2.10 gate-1 component recipe: pinned sources, stage-D bytes and sealed writers."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.fixtures import accepted_policy_fixture_compiler_component_v1 as component


class ComponentSourceTests(unittest.TestCase):
    def test_every_source_is_pinned_and_meets_the_owner_source_rule(self):
        for name in ("c1", "c2", "c3", "c4", "c5"):
            with self.subTest(name=name):
                raw = component.component_source_v1(name)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), component.SOURCE_SHA256[name])
                self.assertTrue(raw.isascii())
                self.assertNotIn(b"\0", raw)
                self.assertTrue(raw.startswith(b'#define STATE_FILE "engine.state"\n'))
                self.assertIn(b"\n#define DAEMON_ID ", raw[:8192])
                self.assertLessEqual(len(raw), component.SOURCE_LIMIT)

    def test_source_drift_is_refused(self):
        with mock.patch.dict(component._BUILDERS, {"c2": lambda: component._header("c2") + "int main(void){return 0;}\n"}):
            with self.assertRaisesRegex(component.ComponentRecipeError, "drift"):
                component.component_source_v1("c2")
        with self.assertRaisesRegex(component.ComponentRecipeError, "unknown"):
            component.component_source_v1("c6")

    def test_failure_sources_have_their_planned_shape(self):
        self.assertIn(b"{1};", component.component_source_v1("c3"))
        self.assertIn(b"[20 << 20]", component.component_source_v1("c3"))
        c4 = component.component_source_v1("c4")
        self.assertEqual(c4.count(b"\n#warning "), 40000)
        self.assertNotIn(b"main", c4)
        self.assertIn(b'#include "/proc/self/fd/1"', component.component_source_v1("c5"))
        self.assertIn(b"return 0 }", component.component_source_v1("c2"))

    def test_stage_d_bytes_are_fixed_and_named_in_c1(self):
        self.assertEqual(component.D_COMMAND, b"VAST-C1-COMMAND-V1\n")
        self.assertEqual(component.D_REPLY, b"VAST-C1-REPLY-V1 vast-component-c1\n")
        c1 = component.component_source_v1("c1")
        self.assertIn(b'"VAST-C1-COMMAND-V1\\n"', c1)
        self.assertIn(b'"VAST-C1-REPLY-V1 " DAEMON_ID "\\n"', c1)
        self.assertIn(b'#define DAEMON_ID "vast-component-c1"', c1)


class SealedWriterTests(unittest.TestCase):
    def review(self):
        return {"commit": "a" * 40, "approval_reference": "PR9 2.10 gate", "evidence_sha256": "b" * 64}

    def test_sealed_json_is_canonical_exclusive_and_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / "seed.json"
            sealed = component.seal_json_v1(path, {"b": 1, "a": [1, 2]})
            raw = path.read_bytes()
            self.assertEqual(raw, b'{"a":[1,2],"b":1}')
            self.assertEqual(sealed, {"path": str(path), "size_bytes": len(raw),
                                      "sha256": hashlib.sha256(raw).hexdigest()})
            with self.assertRaises(FileExistsError):
                component.seal_json_v1(path, {"a": 1})
            with self.assertRaisesRegex(component.ComponentRecipeError, "bound"):
                component.seal_json_v1(Path(tmp).resolve() / "big.json", {"a": "x" * 5000})

    def test_seed_rejects_malformed_facts(self):
        good = dict(review=self.review(), bindings={"host_sha256": "1" * 64, "publisher_sha256": "2" * 64,
                    "profile_sha256": "3" * 64}, engine={"driver": "overlayfs", "cgroup_driver": "systemd",
                    "security_options": ["name=seccomp,profile=builtin"], "runtimes_sha256": "4" * 64},
                    provider={"rootfs_sha256": "5" * 64, "size_bytes": 1}, environment_keys=["A", "B"],
                    mounts_sha256="6" * 64, proofs=dict.fromkeys(("baseline", "toolchain", "abi", "limits", "closure")))
        seed = component.component_seed_v1(**good)
        self.assertEqual(seed["artifact_kind"], "vast_fixture_compiler_component_seed_v1")
        for field, value in (("environment_keys", ["B", "A"]), ("mounts_sha256", "x"),
                             ("proofs", {"baseline": None}), ("review", {"commit": "short"})):
            with self.subTest(field=field), self.assertRaises(component.ComponentRecipeError):
                component.component_seed_v1(**{**good, field: value})

    def test_real_provider_seed_fits_the_sealed_cap(self):
        observed = json.loads((ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/"
                               "compiler-component-01/observations-01/provider-image.v1_55.original.json").read_bytes())
        keys = sorted(entry.split("=", 1)[0] for entry in observed["Config"]["Env"])
        seed = component.component_seed_v1(review=self.review(), bindings={"host_sha256": "1" * 64,
            "publisher_sha256": "2" * 64, "profile_sha256": "3" * 64}, engine={"driver": "overlayfs",
            "cgroup_driver": "systemd", "security_options": ["name=seccomp,profile=builtin", "name=cgroupns"],
            "runtimes_sha256": "4" * 64}, provider={"rootfs_sha256": "5" * 64, "size_bytes": observed["Size"]},
            environment_keys=keys, mounts_sha256="6" * 64,
            proofs=dict.fromkeys(("baseline", "toolchain", "abi", "limits", "closure"), "7" * 64))
        self.assertLessEqual(len(component.canonical_json_v1(seed)), component.SEALED_LIMIT)

    def test_admission_uses_the_plans_fixed_values(self):
        admission = component.component_admission_v1(project_root=Path("/root-x"), review=self.review(),
            seed_sha256="c" * 64, bindings={"host_sha256": "1" * 64, "publisher_sha256": "2" * 64,
            "profile_sha256": "3" * 64}, source_relative="engine.c", source=b"#define STATE_FILE x\n",
            executable_relative="engine", physical_plan_sha256="d" * 64, boot_id="boot", now_unix_ns=10)
        self.assertEqual(admission["scope"], "component_only")
        self.assertIsNone(admission["component_seed"])
        self.assertIsNone(admission["whole_chain_admission_sha256"])
        self.assertEqual(admission["filesystem_floors"], {"c_bytes": 43486543872, "project_bytes": 1073741824})
        self.assertEqual((admission["additional_disk_upper_bytes"], admission["retained_upper_bytes"],
                          admission["metadata_upper_bytes"]), (134217728, 67108864, 262144))
        self.assertEqual(admission["expires_unix_ns"], 10 + 55_000_000_000)
        self.assertLessEqual(len(component.canonical_json_v1(admission)), component.SEALED_LIMIT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
