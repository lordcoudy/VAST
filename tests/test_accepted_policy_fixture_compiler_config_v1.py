"""Pre-create compiler isolation gates; no Docker calls in these tests."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tests.fixtures import accepted_policy_fixture_compiler_v1 as compiler


class CompilerConfigTests(unittest.TestCase):
    def test_selected_containerd_image_id_is_the_manifest_identity(self):
        self.image["Id"] = "sha256:c11befa808af8270e8ea0d0d7cc7cabbda08a2f496ee30b95f7acba5dce81759"
        result = compiler.compiler_container_config_v1(self.image, **self.options)
        self.assertEqual(result["Image"], self.image["Id"])

    def setUp(self):
        self.image = {"Id": "sha256:c11befa808af8270e8ea0d0d7cc7cabbda08a2f496ee30b95f7acba5dce81759",
            "Os": "linux", "Architecture": "amd64", "Config": {"Volumes": None,
                "Labels": {"controlled.provider.%02d" % index: "value-%02d" % index for index in range(23)},
                "Env": ["PATH=/unknown", "LD_PRELOAD=untrusted", "PYTHONPATH=/unknown"]}}
        self.options = {"environment_keys": ["LD_PRELOAD", "PATH", "PYTHONPATH"],
            "publisher_path": "/physical/project/publisher.py", "nonce": "a" * 32,
            "source_sha256": "b" * 64,
            "profile_raw": (Path(__file__).parent / "fixtures/accepted_policy_fixture_compiler_seccomp_v1.json").read_bytes()}

    def test_implicit_image_volumes_refuse_before_any_create(self):
        for volumes in ({"/data": {}}, [], "invalid"):
            with self.subTest(volumes=volumes):
                self.image["Config"]["Volumes"] = volumes
                with self.assertRaises(compiler.FixtureCompilerError):
                    compiler.compiler_container_config_v1(self.image, **self.options)

    def test_environment_drift_and_duplicate_keys_refuse(self):
        for env in (["PATH=x"], ["PATH=x", "LD_PRELOAD=", "PYTHONPATH=", "NEW_IMAGE_KEY=1"],
                    ["PATH=x", "PATH=y", "LD_PRELOAD=", "PYTHONPATH="]):
            with self.subTest(env=env):
                self.image["Config"]["Env"] = env
                with self.assertRaises(compiler.FixtureCompilerError):
                    compiler.compiler_container_config_v1(self.image, **self.options)

    def test_first_exec_environment_overrides_every_image_key(self):
        result = compiler.compiler_container_config_v1(self.image, **self.options)
        env = dict(row.split("=", 1) for row in result["Env"])
        self.assertEqual(env["LD_PRELOAD"], "")
        self.assertEqual(env["PYTHONPATH"], "")
        self.assertEqual(env["PATH"], "/usr/bin:/bin")
        self.assertEqual(result["Entrypoint"], ["/usr/bin/python3", "-I", "-S", "-B", "/fixture/compiler.py"])
        self.assertEqual(result["User"], "1000:1000")

    def test_fixed_quotas_runtime_and_no_writable_host_bind(self):
        result = compiler.compiler_container_config_v1(self.image, **self.options)
        host = result["HostConfig"]
        self.assertEqual((host["Memory"], host["MemorySwap"], host["PidsLimit"], host["NanoCpus"]),
            (536870912, 536870912, 32, 1000000000))
        self.assertEqual((host["Runtime"], host["Init"], host["ReadonlyRootfs"]), ("runc", False, True))
        self.assertEqual(host["Ulimits"], [{"Name": "core", "Soft": 1, "Hard": 1},
            {"Name": "fsize", "Soft": 16777216, "Hard": 16777216}])
        self.assertEqual(len(host["Mounts"]), 1)
        self.assertTrue(host["Mounts"][0]["ReadOnly"])
        self.assertEqual(host["VolumesFrom"], [])
        self.assertIn("size=134217728", host["Tmpfs"]["/work"])
        self.assertIn("nr_inodes=4096", host["Tmpfs"]["/work"])

    def test_profile_or_image_drift_refuses(self):
        options = dict(self.options, profile_raw=b"{}")
        with self.assertRaises(compiler.FixtureCompilerError):
            compiler.compiler_container_config_v1(self.image, **options)
        self.image["Id"] = "sha256:" + "c" * 64
        with self.assertRaises(compiler.FixtureCompilerError):
            compiler.compiler_container_config_v1(self.image, **self.options)

    def test_api_encoding_is_compact_and_preserves_the_complete_pinned_policy(self):
        result = compiler.compiler_container_config_v1(self.image, **self.options)
        value = result["HostConfig"]["SecurityOpt"][1].removeprefix("seccomp=")
        self.assertEqual(len(value.encode("ascii")), 16876)
        self.assertNotIn("\n", value)
        self.assertNotIn("\t", value)
        self.assertEqual(json.loads(value), json.loads(self.options["profile_raw"]))


if __name__ == "__main__":
    unittest.main()
