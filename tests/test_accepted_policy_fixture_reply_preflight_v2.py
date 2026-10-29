"""Complete reply-map and alias bounds before copying; no physical I/O."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from tests.fixtures import accepted_policy_physical_fixture_v2 as physical
from tests.test_accepted_policy_fixture_probe_binding_v2 import artificial_reply_inputs_v2


class ReplyMapPreflightTests(unittest.TestCase):
    def inputs(self):
        return artificial_reply_inputs_v2()

    def call_replies(self, patch_value, images, probes, *, refused=False):
        with patch.object(physical.PhysicalRootCustodyV1, "open") as opened:
            custody = opened.return_value.__enter__.return_value
            opened.return_value.__exit__.return_value = False
            custody.read_descriptor.return_value = ({}, json.dumps(patch_value).encode("ascii"))
            kwargs = dict(identity_patch_path=Path("/controlled/identity.json"),
                image_inspections=images, device_probes=probes)
            if refused:
                with self.assertRaises(ValueError):
                    physical._fixture_command_replies_v2(**kwargs)
                opened.assert_not_called()
                return None
            return physical._fixture_command_replies_v2(**kwargs)

    def test_complete_json_bounds_refuse_before_alias_copy_or_patch_read(self):
        for kind in ("depth", "nodes", "string", "aggregate", "source_table", "nonfinite"):
            with self.subTest(kind=kind):
                patch_value, images, probes = self.inputs()
                image = next(iter(images.values()))
                if kind == "depth":
                    value = None
                    for _ in range(33):
                        value = {"nested": value}
                    image["controlled_extra"] = value
                elif kind == "nodes":
                    image["controlled_extra"] = [[None] * 4096 for _ in range(17)]
                elif kind == "string":
                    image["controlled_extra"] = "A" * (1024**2 + 1)
                elif kind in ("aggregate", "source_table"):
                    image["controlled_extra"] = ["A" * 1024**2] * (9 if kind == "aggregate" else 4)
                else:
                    probes["openvino_gva"]["controlled_extra"] = float("nan")
                self.call_replies(patch_value, images, probes, refused=True)

    def test_image_count_over4096_refuses_before_patch_read(self):
        patch_value, images, probes = self.inputs()
        for number in range(4091):
            image_id = "sha256:" + format(number, "064x")
            images[image_id] = {"Id": image_id, "RepoTags": [], "RepoDigests": []}
        self.assertEqual(len(images), 4097)
        self.call_replies(patch_value, images, probes, refused=True)

    def test_aliases_require_printable_ascii_and_at_most512_characters(self):
        for alias in ("A" * 513, "controlled\talias", "controlled\u00e9alias"):
            with self.subTest(alias=alias):
                patch_value, images, probes = self.inputs()
                next(iter(images.values()))["RepoTags"] = [alias]
                self.call_replies(patch_value, images, probes, refused=True)

    def test_unique_alias_limit_accepts4096_then_refuses4097_before_patch(self):
        patch_value, images, probes = self.inputs()
        image = next(iter(images.values()))
        image["RepoTags"] = ["controlled:" + str(number) for number in range(4079)]
        aliases, _ = self.call_replies(patch_value, images, probes)
        self.assertEqual(len(aliases), 4096)
        # This is only the reply-map stage. The unchanged combined compiler
        # source preflight still decides whether expanded values fit its 8 MiB.
        image["RepoTags"].append("controlled:one-over")
        self.call_replies(patch_value, images, probes, refused=True)

    def test_duplicate_references_do_not_consume_unique_alias_slots(self):
        patch_value, images, probes = self.inputs()
        image = next(iter(images.values()))
        image["RepoTags"] = ["controlled:duplicate"] * 4096
        image["RepoDigests"] = ["controlled:duplicate"] * 4096
        aliases, _ = self.call_replies(patch_value, images, probes)
        self.assertIs(aliases["controlled:duplicate"], image)
        self.assertLess(len(aliases), 4096)

    def test_valid_original_values_and774_character_environment_are_preserved(self):
        patch_value, images, probes = self.inputs()
        image_id, image = next(iter(images.items()))
        image["Config"]["Env"] = ["PATH=" + "a" * 769]
        image["RepoTags"] = ["A" * 512]
        before = deepcopy((images, probes))
        aliases, replies = self.call_replies(patch_value, images, probes)
        self.assertEqual((images, probes), before)
        self.assertEqual(len(image["Config"]["Env"][0]), 774)
        self.assertIs(aliases[image_id], image)
        self.assertIs(aliases["A" * 512], image)
        self.assertIs(replies[image_id], probes["openvino_gva"])


if __name__ == "__main__":
    unittest.main()
