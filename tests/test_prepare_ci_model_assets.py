from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import prepare_ci_model_assets as assets


class Response(io.BytesIO):
    def __init__(self, body, url, *, status=200, length=None):
        super().__init__(body)
        self.status = status
        self.url = url
        self.headers = {"Content-Length": str(len(body) if length is None else length)}

    def geturl(self):
        return self.url


class PrepareCiModelAssetsTests(unittest.TestCase):
    """Local tiny bodies exercise custody/transfer, not canonical model acceptance."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="vast-ci-assets-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / ".ci").mkdir()
        (self.root / "configs").mkdir()
        self.manifest = yaml.safe_load((ROOT / "configs/checkpoint_analytics_models_openvino.yaml").read_text())
        self.inventory = json.loads((ROOT / ".ci/model-assets.v1.json").read_text())
        self.bodies = {}
        for row in self.inventory["assets"]:
            body = ("local-fixture:" + row["branch"] + ":" + row["role"]).encode()
            self.bodies[row["url"]] = body
            row["size_bytes"] = len(body)
            row["sha256"] = hashlib.sha256(body).hexdigest()
            row["sha384"] = hashlib.sha384(body).hexdigest()
            branch = self.manifest["branches"][row["branch"]]
            prefix = "model" if row["role"] == "xml" else "weights"
            branch[prefix + "_sha256"] = row["sha256"]
            branch[prefix + "_source_sha384"] = row["sha384"]
        self.write_inputs()
        self.calls = []

    def write_inputs(self):
        raw = yaml.safe_dump(self.manifest, sort_keys=False).encode()
        (self.root / "configs/checkpoint_analytics_models_openvino.yaml").write_bytes(raw)
        self.inventory["manifest"]["size_bytes"] = len(raw)
        self.inventory["manifest"]["sha256"] = hashlib.sha256(raw).hexdigest()
        (self.root / ".ci/model-assets.v1.json").write_text(json.dumps(self.inventory))

    def opener(self, request, *, timeout):
        url = request.full_url
        self.calls.append((url, timeout))
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 15)
        return Response(self.bodies[url], url)

    def run_preparation(self, opener=None):
        return assets.prepare_ci_model_assets(project_root=self.root,
            output_dir=self.root / "observations", opener=opener or self.opener)

    def test_clean_empty_checkout_acquires_exact_eight_without_input_changes(self):
        before = {path: path.read_bytes() for path in (self.root / ".ci/model-assets.v1.json",
            self.root / "configs/checkpoint_analytics_models_openvino.yaml")}
        result = self.run_preparation()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(result["assets"]), 8)
        self.assertEqual({url for url, _ in self.calls}, set(self.bodies))
        for row in self.inventory["assets"]:
            target = self.root / row["path"]
            self.assertEqual(target.read_bytes(), self.bodies[row["url"]])
            self.assertEqual(target.stat().st_nlink, 1)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertFalse(result["hardware_acceptance"])

    def test_correct_existing_objects_are_verified_without_network(self):
        for row in self.inventory["assets"]:
            target = self.root / row["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.bodies[row["url"]])
        result = self.run_preparation()
        self.assertEqual(self.calls, [])
        self.assertTrue(all(row["status"] == "reused" for row in result["assets"]))

    def test_corrupt_cache_is_not_overwritten_and_prevents_dispatch(self):
        target = self.root / self.inventory["assets"][0]["path"]
        target.parent.mkdir(parents=True)
        target.write_bytes(b"corrupt")
        with self.assertRaisesRegex(assets.AssetPreparationError, "existing.*size|existing.*digest"):
            self.run_preparation()
        self.assertEqual(target.read_bytes(), b"corrupt")
        self.assertEqual(self.calls, [])

    def test_symlink_model_parent_is_rejected_without_outside_write(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.root / "models").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(assets.AssetPreparationError, "symlink|physical|alias"):
            self.run_preparation()
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(self.calls, [])

    def test_existing_hardlink_is_rejected(self):
        target = self.root / self.inventory["assets"][0]["path"]
        target.parent.mkdir(parents=True)
        target.write_bytes(self.bodies[self.inventory["assets"][0]["url"]])
        os.link(target, self.root / "second-name")
        with self.assertRaisesRegex(assets.AssetPreparationError, "single|alias|link"):
            self.run_preparation()

    def test_metadata_path_escape_is_rejected_before_dispatch(self):
        self.inventory["assets"][0]["path"] = "../outside.xml"
        self.write_inputs()
        with self.assertRaisesRegex(assets.AssetPreparationError, "destination|path|canonical"):
            self.run_preparation()
        self.assertEqual(self.calls, [])

    def test_wrong_digest_preserves_original_failed_partial(self):
        first = self.inventory["assets"][0]
        def wrong(request, *, timeout):
            self.calls.append((request.full_url, timeout))
            return Response(b"x" * first["size_bytes"], request.full_url)
        with self.assertRaisesRegex(assets.AssetPreparationError, "digest"):
            self.run_preparation(wrong)
        self.assertFalse((self.root / first["path"]).exists())
        record = json.loads((self.root / "observations/asset-00.json").read_text())
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["received_bytes"], first["size_bytes"])
        self.assertTrue(Path(record["partial_path"]).is_file())

    def test_short_and_oversize_bodies_never_publish(self):
        first = self.inventory["assets"][0]
        for suffix, body in (("short", b"s"), ("large", b"x" * (first["size_bytes"] + 1))):
            with self.subTest(suffix=suffix):
                output = self.root / suffix
                def wrong(request, *, timeout):
                    return Response(body, request.full_url, length=first["size_bytes"])
                with self.assertRaisesRegex(assets.AssetPreparationError, "size|short|oversize"):
                    assets.prepare_ci_model_assets(project_root=self.root, output_dir=output, opener=wrong)
                self.assertFalse((self.root / first["path"]).exists())

    def test_http_error_redirect_and_timeout_are_original_failures(self):
        first = self.inventory["assets"][0]
        for label in ("status", "redirect", "timeout"):
            with self.subTest(label=label):
                def failing(request, *, timeout):
                    if label == "timeout":
                        raise TimeoutError("original fixture read timeout")
                    return Response(self.bodies[first["url"]],
                        first["url"] if label == "status" else "https://foreign.invalid/model.xml",
                        status=503 if label == "status" else 200)
                with self.assertRaisesRegex(assets.AssetPreparationError, "status|redirect|timeout"):
                    assets.prepare_ci_model_assets(project_root=self.root, output_dir=self.root / label,
                        opener=failing)
                self.assertFalse((self.root / first["path"]).exists())

    def test_publication_race_never_replaces_foreign_target(self):
        first = self.inventory["assets"][0]
        target = self.root / first["path"]
        def racer(request, *, timeout):
            target.write_bytes(b"foreign-owner")
            return Response(self.bodies[first["url"]], request.full_url)
        with self.assertRaisesRegex(assets.AssetPreparationError, "exist|replace|occupied"):
            self.run_preparation(racer)
        self.assertEqual(target.read_bytes(), b"foreign-owner")

    def test_manifest_drift_during_transfer_blocks_publication(self):
        first = self.inventory["assets"][0]
        def drifting(request, *, timeout):
            path = self.root / "configs/checkpoint_analytics_models_openvino.yaml"
            path.write_bytes(path.read_bytes() + b"\n# changed during original transfer\n")
            return Response(self.bodies[first["url"]], request.full_url)
        with self.assertRaisesRegex(assets.AssetPreparationError, "input|manifest|changed|drift"):
            self.run_preparation(drifting)
        self.assertFalse((self.root / first["path"]).exists())

    def test_large_body_uses_only_bounded_reads(self):
        first = self.inventory["assets"][0]
        body = b"z" * (2 * assets.CHUNK_BYTES + 21)
        self.bodies[first["url"]] = body
        first["size_bytes"] = len(body)
        first["sha256"] = hashlib.sha256(body).hexdigest()
        first["sha384"] = hashlib.sha384(body).hexdigest()
        branch = self.manifest["branches"][first["branch"]]
        branch["model_sha256"] = first["sha256"]
        branch["model_source_sha384"] = first["sha384"]
        self.write_inputs()
        reads = []
        class Tracked(Response):
            def read(self, size=-1):
                reads.append(size)
                return super().read(size)
        def tracked(request, *, timeout):
            return Tracked(self.bodies[request.full_url], request.full_url)
        self.run_preparation(tracked)
        self.assertEqual(max(reads), 64 * 1024)
        self.assertTrue(all(0 < size <= 64 * 1024 for size in reads))

    def test_namespace_budget_and_occupied_observations_fail_before_dispatch(self):
        self.inventory["assets"][0]["size_bytes"] = assets.NAMESPACE_BYTES
        self.write_inputs()
        with self.assertRaisesRegex(assets.AssetPreparationError, "budget"):
            self.run_preparation()
        self.assertEqual(self.calls, [])
        self.inventory["assets"][0]["size_bytes"] = len(self.bodies[self.inventory["assets"][0]["url"]])
        self.write_inputs()
        (self.root / "observations").mkdir()
        marker = self.root / "observations/original"
        marker.write_bytes(b"preserve")
        with self.assertRaisesRegex(assets.AssetPreparationError, "occupied"):
            self.run_preparation()
        self.assertEqual(marker.read_bytes(), b"preserve")

    def test_real_http_error_keeps_status_and_redirect_without_retry(self):
        first = self.inventory["assets"][0]
        calls = []
        def redirect(request, *, timeout):
            calls.append(request.full_url)
            raise urllib.error.HTTPError(request.full_url, 302, "original redirect", {
                "Location": "https://user:secret@foreign.invalid/object?token=secret"}, None)
        with self.assertRaisesRegex(assets.AssetPreparationError, "302|redirect"):
            self.run_preparation(redirect)
        self.assertEqual(calls, [first["url"]])
        record = json.loads((self.root / "observations/asset-00.json").read_text())
        self.assertEqual(record["http_status"], 302)
        self.assertTrue(record["redirect_rejected"])
        self.assertNotIn("secret", json.dumps(record["response_headers"]))

    def test_real_original_child_timeout_is_reaped_in_outer_group(self):
        command = [sys.executable, "-I", "-B", "-c", "import time; time.sleep(20)"]
        began = time.monotonic()
        with mock.patch.object(assets, "_worker_command", return_value=command), \
                mock.patch.object(assets, "OBJECT_SECONDS", 0.25), \
                mock.patch.object(assets, "TEARDOWN_SECONDS", 0.1), \
                mock.patch.object(assets, "TOTAL_SECONDS", 1.0):
            with self.assertRaisesRegex(assets.AssetPreparationError, "timeout"):
                assets.prepare_ci_model_assets(project_root=self.root, output_dir=self.root / "observations")
        self.assertLess(time.monotonic() - began, 3)
        terminal = json.loads((self.root / "observations/asset-00.terminal.json").read_text())
        self.assertTrue(terminal["timed_out"])
        self.assertEqual(terminal["returncode"], -9)
        self.assertTrue(terminal["child_inherits_original_group"])
        self.assertFalse(Path(f"/proc/{terminal['pid']}").exists())

    def test_record_text_is_bounded_even_for_large_unicode_error(self):
        def failing(request, *, timeout):
            raise TimeoutError("\U0001f680" * 10000)
        with self.assertRaises(assets.AssetPreparationError):
            self.run_preparation(failing)
        path = self.root / "observations/asset-00.json"
        self.assertLessEqual(path.stat().st_size, assets.RECORD_BYTES)
        record = json.loads(path.read_text())
        self.assertTrue(record["error"]["message_truncated"])
        self.assertTrue(record["error"]["traceback_truncated"])

    def test_real_reader_socket_wait_is_reduced_to_remaining_deadline(self):
        calls = []
        value = [0.0]
        def clock():
            value[0] += 0.01
            return value[0]
        def local(request, *, timeout):
            response = Response(self.bodies[request.full_url], request.full_url)
            response.fp = SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(
                settimeout=lambda seconds: calls.append(seconds))))
            return response
        with mock.patch.object(assets, "_network_open", local), \
                mock.patch.object(assets, "OBJECT_SECONDS", 10.5), \
                mock.patch.object(assets, "TEARDOWN_SECONDS", 10):
            result = assets.prepare_ci_model_assets(project_root=self.root, output_dir=self.root / "observations",
                opener=local, clock=clock)
        self.assertEqual(result["status"], "complete")
        self.assertTrue(calls)
        self.assertTrue(all(0 < seconds <= 0.5 for seconds in calls))

    def test_redirect_handler_never_creates_a_followup_request(self):
        self.assertIsNone(assets._NoRedirect().redirect_request(None, None, 302, "redirect", {},
            "https://foreign.invalid/object"))

    def test_existing_file_growth_is_stopped_at_exact_size_cap(self):
        first = self.inventory["assets"][0]
        target = self.root / first["path"]
        target.parent.mkdir(parents=True)
        target.write_bytes(self.bodies[first["url"]])
        original = hashlib.new
        grew = []
        class Digest:
            def __init__(self, name):
                self.real = original(name)
            def update(self, block):
                self.real.update(block)
                if not grew:
                    grew.append(True)
                    with target.open("ab") as stream:
                        stream.write(b"growth")
            def hexdigest(self):
                return self.real.hexdigest()
        with mock.patch.object(assets.hashlib, "new", side_effect=Digest):
            with self.assertRaisesRegex(assets.AssetPreparationError, "size cap"):
                self.run_preparation()
        self.assertEqual(self.calls, [])

    def test_external_fresh_observations_keep_repository_destinations_fixed(self):
        with tempfile.TemporaryDirectory(prefix="vast-ci-assets-observations-") as external:
            output = Path(external) / "nested" / "observations"
            result = assets.prepare_ci_model_assets(project_root=self.root,
                output_dir=output, opener=self.opener)
            self.assertEqual(result["status"], "complete")
            self.assertTrue((output / "report.json").is_file())
            for row in self.inventory["assets"]:
                self.assertEqual((self.root / row["path"]).read_bytes(), self.bodies[row["url"]])
            self.assertFalse((Path(external) / "models").exists())

    def test_external_output_absolute_path_is_passed_to_original_child(self):
        with tempfile.TemporaryDirectory(prefix="vast-ci-assets-child-output-") as external:
            output = Path(external) / "observations"
            original_command = assets._worker_command
            observed = []
            def fixture_command(index, actual_output, staging, deadline):
                command = original_command(index, actual_output, staging, deadline)
                observed.append(command)
                self.assertEqual(command[command.index("--output-dir") + 1], str(output))
                return [sys.executable, "-I", "-B", "-c", "import time; time.sleep(20)"]
            with mock.patch.object(assets, "_worker_command", side_effect=fixture_command), \
                    mock.patch.object(assets, "OBJECT_SECONDS", 0.25), \
                    mock.patch.object(assets, "TEARDOWN_SECONDS", 0.1), \
                    mock.patch.object(assets, "TOTAL_SECONDS", 1.0):
                with self.assertRaisesRegex(assets.AssetPreparationError, "timeout"):
                    assets.prepare_ci_model_assets(project_root=self.root, output_dir=output)
            self.assertEqual(len(observed), 1)
            terminal = json.loads((output / "asset-00.terminal.json").read_text())
            self.assertTrue(terminal["timed_out"])
            self.assertEqual(terminal["returncode"], -9)
            self.assertFalse(Path(f"/proc/{terminal['pid']}").exists())

    def test_same_bytes_partial_replacement_is_not_published_as_original(self):
        original_link = os.link
        replacement = []
        def substitute(source, destination, **kwargs):
            directory = Path(os.readlink(f"/proc/self/fd/{kwargs['src_dir_fd']}"))
            partial = directory / source
            original_bytes = partial.read_bytes()
            partial.rename(directory / "original-partial")
            partial.write_bytes(original_bytes)
            replacement.append(partial)
            return original_link(source, destination, **kwargs)
        with mock.patch.object(assets.os, "link", side_effect=substitute):
            with self.assertRaisesRegex(assets.AssetPreparationError, "original|inode|replaced"):
                self.run_preparation()
        self.assertEqual(len(replacement), 1)
        self.assertEqual(replacement[0].read_bytes(), self.bodies[self.inventory["assets"][0]["url"]])
        self.assertFalse((self.root / "observations/report.json").exists())
        record = json.loads((self.root / "observations/asset-00.json").read_text())
        self.assertFalse(record["partial_path_matches_original_fd"])

    def test_failed_write_labels_received_hash_separately_from_observed_file_size(self):
        original_fdopen = os.fdopen
        class BrokenWrite:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.stream.close()
            def write(self, block):
                self.stream.write(block[:3])
                self.stream.flush()
                raise OSError("original fixture partial write")
            def flush(self):
                self.stream.flush()
        def fdopen(descriptor, *args, **kwargs):
            stream = original_fdopen(descriptor, *args, **kwargs)
            if os.readlink(f"/proc/self/fd/{descriptor}").endswith(".part"):
                return BrokenWrite(stream)
            return stream
        with mock.patch.object(assets.os, "fdopen", side_effect=fdopen):
            with self.assertRaisesRegex(assets.AssetPreparationError, "partial write"):
                self.run_preparation()
        row = self.inventory["assets"][0]
        record = json.loads((self.root / "observations/asset-00.json").read_text())
        self.assertEqual(record["hashed_prefix_bytes"], row["size_bytes"])
        self.assertEqual(record["received_prefix_sha256"], row["sha256"])
        self.assertEqual(record["completed_write_bytes"], 0)
        self.assertEqual(record["original_file_observed_bytes"], 3)
        self.assertNotIn("stored_prefix_sha256", record)

    def test_deadline_is_rechecked_after_final_report_fsync(self):
        current = [0.0]
        original_write = assets._write_json
        def delayed_report(directory, name, value):
            original_write(directory, name, value)
            if name == "report.json":
                current[0] = assets.TOTAL_SECONDS + 1
        with mock.patch.object(assets, "_write_json", side_effect=delayed_report):
            with self.assertRaisesRegex(assets.AssetPreparationError, "deadline"):
                assets.prepare_ci_model_assets(project_root=self.root,
                    output_dir=self.root / "observations", opener=self.opener,
                    clock=lambda: current[0])
        self.assertEqual(json.loads((self.root / "observations/failed.json").read_text())["status"], "failed")

    def test_external_observation_alias_and_occupied_leaf_preserve_existing_files(self):
        with tempfile.TemporaryDirectory(prefix="vast-ci-assets-output-alias-") as external:
            anchor = Path(external)
            (anchor / "actual").mkdir()
            (anchor / "alias").symlink_to(anchor / "actual", target_is_directory=True)
            with self.assertRaisesRegex(assets.AssetPreparationError, "physical|alias"):
                assets.prepare_ci_model_assets(project_root=self.root,
                    output_dir=anchor / "alias" / "observations", opener=self.opener)
            (anchor / "occupied").mkdir()
            marker = anchor / "occupied" / "original"
            marker.write_bytes(b"preserve original")
            with self.assertRaisesRegex(assets.AssetPreparationError, "occupied"):
                assets.prepare_ci_model_assets(project_root=self.root,
                    output_dir=anchor / "occupied", opener=self.opener)
            self.assertEqual(marker.read_bytes(), b"preserve original")
            self.assertFalse((anchor / "actual" / "observations").exists())
            self.assertEqual(self.calls, [])

    def test_original_worker_opens_external_output_without_model_root_override(self):
        with tempfile.TemporaryDirectory(prefix="vast-ci-assets-worker-output-") as external:
            output = Path(external) / "observations"
            output.mkdir()
            staging = "models/.ci-acquisition-0000000000000000"
            (self.root / staging).mkdir(parents=True)
            first = self.inventory["assets"][0]
            (self.root / first["path"]).parent.mkdir(parents=True)
            with mock.patch.object(assets, "ROOT", self.root), \
                    mock.patch.object(assets, "_network_open", self.opener), \
                    mock.patch.object(assets, "_read_timeout"):
                result = assets.main(["--output-dir", str(output), "--_asset", "0", "--_staging", staging,
                    "--_deadline", str(time.monotonic() + 30)])
            self.assertEqual(result, 0)
            self.assertEqual((self.root / first["path"]).read_bytes(), self.bodies[first["url"]])
            self.assertEqual(json.loads((output / "asset-00.json").read_text())["status"], "downloaded")
            self.assertFalse((Path(external) / "models").exists())


if __name__ == "__main__":
    unittest.main()
