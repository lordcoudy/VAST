"""B1 restore checks with fake docker/ctr executables and a synthetic OCI archive.

No Docker daemon, containerd or real image is touched: the fake CLIs are small
Python programs driven by a JSON state file, the native Engine API is an
in-process fake, and the archive is a tiny synthetic image with its own pins.
The real bounded runner, archive verifier and record writer are exercised.
"""
from __future__ import annotations

import dataclasses
import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import re
import signal
import socketserver
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import accepted_policy_b1_restore_v1 as b1  # noqa: E402

OCI_INDEX = "application/vnd.oci.image.index.v1+json"
FAKE_DOCKER = r'''
import json, os, sys, time
state = json.load(open(os.environ["B1_FAKE_STATE"]))
args = sys.argv[1:]
log = state.get("log")
if log:
    with open(log, "a") as handle:
        handle.write(json.dumps(["docker"] + args) + "\n")
if args[:2] != ["-H", state["desktop_host"]]:
    sys.exit(97)
args = args[2:]
if args[:1] == ["version"]:
    print(state["desktop_version"])
elif args[:1] == ["info"]:
    print(state["desktop_id"])
elif args[:2] == ["image", "inspect"]:
    if state.get("source") is None:
        sys.stderr.write("Error: No such image\n"); sys.exit(1)
    print(state["source"])
elif args[:2] == ["image", "save"]:
    time.sleep(state.get("save_sleep", 0))
    data = open(state["archive"], "rb").read()
    out = sys.stdout.buffer
    for i in range(0, len(data), 4096):
        out.write(data[i:i + 4096])
    out.write(b"\0" * state.get("save_pad", 0))
    out.flush()
    sys.exit(state.get("save_rc", 0))
else:
    sys.exit(98)
'''
FAKE_CTR = r'''
import json, os, sys
path = os.environ["B1_FAKE_STATE"]
state = json.load(open(path))
args = sys.argv[1:]
log = state.get("log")
if log:
    with open(log, "a") as handle:
        handle.write(json.dumps(["ctr"] + args) + "\n")
if args[:2] != ["--address", state["address"]]:
    sys.exit(97)
args = args[2:]
if args == ["version"]:
    print(state["ctr_version_text"])
    sys.exit(0)
if args[:2] != ["--namespace", state["namespace"]]:
    sys.exit(96)
args = args[2:]
if args == ["images", "ls", "-q"]:
    print("\n".join(state["refs"]))
elif args == ["content", "active"]:
    print(state.get("ingests", "REF\tSIZE\tAGE"))
elif args == ["leases", "ls"]:
    print(state.get("leases", "ID CREATED AT LABELS"))
elif args[:2] == ["images", "import"]:
    import tarfile
    with tarfile.open(args[-1]) as tar:
        child = json.load(tar.extractfile("index.json"))["manifests"][0]
    named = (child.get("annotations") or {}).get("io.containerd.image.name")
    if named:
        state["refs"].append(named)
    if state.get("import_extra_ref"):
        state["refs"].append(state["import_extra_ref"])
    if state.get("import_mutates_archive"):
        with open(args[-1], "ab") as handle:
            handle.write(b"x")
    rc = state.get("import_rc", 0)
    if rc == 0:
        if not state.get("import_no_ref"):
            state["refs"].append(state["provider"])
        state["imported"] = True
        json.dump(state, open(path, "w"))
    sys.exit(rc)
else:
    sys.exit(98)
'''


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def build_image(layer_sizes=(1000, 2000, 3000), platform="amd64", config_arch="amd64"):
    layers = [bytes([65 + i]) * n for i, n in enumerate(layer_sizes)]
    config = json.dumps({"architecture": config_arch, "os": "linux",
                         "rootfs": {"type": "layers", "diff_ids": [digest(b"diff%d" % i) for i in range(len(layers))]},
                         }).encode()
    manifest = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
                           "config": {"digest": digest(config), "size": len(config)},
                           "layers": [{"digest": digest(x), "size": len(x)} for x in layers]}).encode()
    index = json.dumps({"schemaVersion": 2, "mediaType": OCI_INDEX, "manifests": [
        {"digest": digest(manifest), "size": len(manifest), "platform": {"architecture": platform, "os": "linux"}},
        {"digest": "sha256:" + "9" * 64, "size": 5, "platform": {"architecture": "arm64", "os": "linux"}}]}).encode()
    return {"layers": layers, "config": config, "manifest": manifest, "index": index}


def write_archive(path: Path, img: dict, *, extra=(), drop=(), corrupt=None, symlink=None, child=None,
                  legacy=None, duplicate=None, layout=b'{"imageLayoutVersion":"1.0.0"}', no_legacy=False) -> None:
    blobs = [img["index"], img["manifest"], img["config"], *img["layers"]]
    child = child or {"mediaType": OCI_INDEX, "digest": digest(img["index"]), "size": len(img["index"]),
                      "annotations": {"containerd.io/distribution.source.example.test": "base"}}
    if legacy is None:
        legacy = [{"Config": "blobs/sha256/" + digest(img["config"])[7:], "RepoTags": None,
                   "Layers": ["blobs/sha256/" + digest(x)[7:] for x in img["layers"]]}]
    with tarfile.open(path, "w", format=tarfile.PAX_FORMAT) as tar:
        def add(name, data, kind=tarfile.REGTYPE, target=""):
            info = tarfile.TarInfo(name)
            info.type = kind
            info.mode = 0o644
            if kind == tarfile.REGTYPE:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            else:
                info.linkname = target
                tar.addfile(info)

        add("blobs/", b"", tarfile.DIRTYPE)
        add("blobs/sha256/", b"", tarfile.DIRTYPE)
        for blob in blobs:
            name = "blobs/sha256/" + digest(blob)[7:]
            if name in drop:
                continue
            add(name, corrupt if (corrupt is not None and blob is img["layers"][0]) else blob)
        if duplicate:
            add(duplicate, img["layers"][0])
        add("index.json", json.dumps({"schemaVersion": 2, "manifests": [child]}).encode())
        if not no_legacy:
            add("manifest.json", json.dumps(legacy).encode())
        add("oci-layout", layout)
        for name, data in extra:
            add(name, data)
        if symlink:
            add(symlink, b"", tarfile.SYMTYPE, "index.json")


def native_image(img: dict, pins: b1.Pins) -> dict:
    return {"Id": pins.provider_id, "RepoDigests": [pins.provider], "RepoTags": [pins.provider],
            "Size": pins.native_size,
            "RootFS": {"Type": "layers", "Layers": json.loads(img["config"])["rootfs"]["diff_ids"]},
            "Config": {"Env": ["PATH=/bin", "A=1"]},
            "Manifests": [{"ID": pins.manifest_digest, "Available": True, "ImageData": {"Size": {"Unpacked": 4242}}}]}


class Fixture:
    """A temporary world: fake CLIs, state file, synthetic archive, pins and fake API."""

    def __init__(self, tmp: Path, img=None, **pin_overrides):
        self.tmp = tmp
        self.img = img or build_image()
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        self.docker, self.ctr = bin_dir / "docker", bin_dir / "ctr"
        for path, code in ((self.docker, FAKE_DOCKER), (self.ctr, FAKE_CTR)):
            path.write_text(f"#!{sys.executable}\n{code}")
            path.chmod(0o755)
        self.archive = tmp / "source.tar"
        write_archive(self.archive, self.img)
        content = sum(len(b) for b in [self.img["index"], self.img["manifest"], self.img["config"], *self.img["layers"]])
        provider_id = digest(self.img["index"])
        env_keys = sorted(["PATH", "A"])
        rootfs = {"Type": "layers", "Layers": json.loads(self.img["config"])["rootfs"]["diff_ids"]}
        pins = dict(provider="example.test/base@" + provider_id, base_name="example.test/base",
                    provider_id=provider_id, index_size=len(self.img["index"]),
                    manifest_digest=digest(self.img["manifest"]), manifest_size=len(self.img["manifest"]),
                    config_digest=digest(self.img["config"]), config_size=len(self.img["config"]),
                    layer_count=3, blob_count=6, content_bytes=content, archive_ceiling=1024 * 1024,
                    desktop_host="unix:///fake/desktop.sock", desktop_engine_id="desk-1", desktop_version="29.8.2",
                    native_engine_id="native-1", native_version="29.7.2", containerd_address="/fake/containerd.sock",
                    containerd_version="v2.3.3", containerd_revision="a" * 40, namespace="moby",
                    native_size=content,
                    rootfs_sha256=hashlib.sha256(b1.canonical_json_v1(rootfs)).hexdigest(),
                    env_keys_sha256=hashlib.sha256(b1.canonical_json_v1(env_keys)).hexdigest(),
                    unpacked_bytes=4242, chain_id=b1.chain_id(rootfs["Layers"]),
                    archive_dir=str(tmp / "b1"), archive_name="base.docker-save.tar",
                    deadline_seconds=30.0, docker=str(self.docker), ctr=str(self.ctr), require_root=False)
        pins.update(pin_overrides)
        self.pins = b1.Pins(**pins)
        self.state_path = tmp / "state.json"
        self.log = tmp / "calls.log"
        self.state = {
            "desktop_host": self.pins.desktop_host, "desktop_version": "29.8.2", "desktop_id": "desk-1",
            "source": json.dumps(provider_id) + " " + json.dumps([self.pins.provider]),
            "archive": str(self.archive), "address": self.pins.containerd_address, "namespace": "moby",
            "ctr_version_text": ("Client:\n  Version:  v2.3.3\n  Revision: " + "a" * 40 + "\n\nServer:\n  Version:  v2.3.3\n"
                                 "  Revision: " + "a" * 40 + "\n  UUID: x\n"),
            "refs": [], "provider": self.pins.provider, "log": str(self.log),
        }
        self.api_state = {"version": "29.7.2", "id": "native-1", "image": native_image(self.img, self.pins),
                          "desktop_manifests": [
                              {"ID": self.pins.manifest_digest, "Kind": "image", "Available": True},
                              {"ID": "sha256:" + "9" * 64, "Kind": "image", "Available": False}],
                          "containers": [{"Id": "c" * 64, "State": "exited"}], "containers_after": None,
                          "image_present": False}
        self.save()

    def save(self):
        self.state_path.write_text(json.dumps(self.state))

    def api_get(self, path, timeout):
        s = self.api_state
        imported = json.loads(self.state_path.read_text()).get("imported") or s["image_present"]
        if path == "/v1.55/version":
            return 200, {"Version": s["version"]}
        if path == "/v1.55/info":
            return 200, {"ID": s["id"]}
        if path == "/v1.55/containers/json?all=1":
            rows = s["containers_after"] if (imported and s["containers_after"] is not None) else s["containers"]
            return 200, rows
        if path.startswith(f"/v1.55/images/{self.pins.provider_id}/json"):
            return (200, s["image"]) if imported else (404, {"message": "No such image"})
        raise AssertionError(path)

    def desktop_api_get(self, path, timeout):
        if path == f"/v1.55/images/{self.pins.provider_id}/json?manifests=1":
            return 200, {"Id": self.pins.provider_id, "Manifests": self.api_state["desktop_manifests"]}
        raise AssertionError(path)

    def run(self, reuse=None):
        old = os.environ.get("B1_FAKE_STATE")
        os.environ["B1_FAKE_STATE"] = str(self.state_path)
        try:
            return b1.Restore(self.pins, self.api_get, self.desktop_api_get, reuse=reuse).run()
        finally:
            if old is None:
                os.environ.pop("B1_FAKE_STATE", None)
            else:
                os.environ["B1_FAKE_STATE"] = old

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def imports(self):
        return [c for c in self.calls() if c[:1] == ["ctr"] and "import" in c]

    def saves(self):
        return [c for c in self.calls() if c[:1] == ["docker"] and "save" in c]

    @property
    def target(self) -> Path:
        return Path(self.pins.archive_dir, self.pins.archive_name)


class RestoreTests(unittest.TestCase):
    def fixture(self, img=None, **kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Fixture(Path(tmp.name), img, **kw)

    def test_happy_path_runs_the_reviewed_import_and_verifies_the_native_contract(self):
        f = self.fixture()
        record = f.run()
        self.assertEqual(record["outcome"], "restored", record)
        self.assertEqual(f.imports(), [["ctr", "--address", "/fake/containerd.sock", "--namespace", "moby", "images",
                                        "import", "--local", "--base-name", "example.test/base", "--digests",
                                        "--platform", "linux/amd64", "--snapshotter", "overlayfs", "--sync-fs",
                                        str(f.target)]])
        self.assertEqual(f.saves(), [["docker", "-H", "unix:///fake/desktop.sock", "image", "save", f.pins.provider]])
        self.assertEqual(f.target.read_bytes(), f.archive.read_bytes())  # archive retained
        self.assertEqual(record["archive"]["blobs"], 6)
        self.assertEqual(record["archive"]["members"], 11)
        self.assertEqual(record["archive"]["sha256"], hashlib.sha256(f.archive.read_bytes()).hexdigest())
        self.assertEqual([s["stage"] for s in record["stages"]],
                         ["preflight", "archive_dir_created", "archive_created", "saved", "verified", "imported",
                          "native_verified"])
        self.assertEqual(record["native_containers_before"], record["native_containers_after"])
        self.assertEqual(record["native_references_after"], [f.pins.provider])
        self.assertEqual(record["native_image"]["repo_tags"], [f.pins.provider])

    def test_desktop_is_only_read(self):
        f = self.fixture()
        f.run()
        verbs = [tuple(c[3:5]) if c[3] in ("image",) else (c[3],) for c in f.calls() if c[0] == "docker"]
        self.assertEqual(verbs, [("version",), ("info",), ("image", "inspect"), ("image", "save")])

    def refused_before_writes(self, f, cause):
        record = f.run()
        self.assertEqual((record["outcome"], record["cause"]), ("refused", cause), record)
        self.assertFalse(Path(f.pins.archive_dir).exists())
        self.assertEqual(f.saves(), [])
        self.assertEqual(f.imports(), [])
        return record

    def test_identity_refusals_happen_before_any_write(self):
        cases = {
            "desktop_version": lambda f: f.state.update(desktop_version="29.8.3"),
            "desktop_engine_identity": lambda f: f.state.update(desktop_id="other"),
            "desktop_source_missing": lambda f: f.state.update(source=None),
            "desktop_source_identity": lambda f: f.state.update(source=json.dumps("sha256:" + "0" * 64) + " []"),
            "native_version": lambda f: f.api_state.update(version="29.8.2"),
            "native_engine_identity": lambda f: f.api_state.update(id="desk-1"),
            "native_image_present": lambda f: f.api_state.update(image_present=True),
            "desktop_extra_content": lambda f: f.api_state["desktop_manifests"][1].update(Available=True),
            "desktop_manifests_unreadable": lambda f: f.api_state.update(desktop_manifests=None),
            "containerd_version": lambda f: f.state.update(ctr_version_text=f.state["ctr_version_text"].replace(
                "Server:\n  Version:  v2.3.3", "Server:\n  Version:  v2.3.4")),
            "native_reference_present": lambda f: f.state.update(refs=[f.pins.provider]),
        }
        for cause, mutate in cases.items():
            with self.subTest(cause=cause):
                f = self.fixture()
                mutate(f)
                f.save()
                self.refused_before_writes(f, cause)

    def test_containerd_client_revision_alone_does_not_pass(self):
        f = self.fixture()
        text = f.state["ctr_version_text"]
        server = text.index("Server:")
        f.state["ctr_version_text"] = text[:server] + text[server:].replace("a" * 40, "b" * 40)
        f.save()
        self.refused_before_writes(f, "containerd_version")

    def test_containerd_client_version_is_pinned_too(self):
        f = self.fixture()
        f.state["ctr_version_text"] = f.state["ctr_version_text"].replace("Client:\n  Version:  v2.3.3",
                                                                          "Client:\n  Version:  v2.3.4")
        f.save()
        self.refused_before_writes(f, "containerd_version")

    def test_missing_or_null_repo_tags_is_drift(self):
        for value in (None, []):
            with self.subTest(value=value):
                f = self.fixture()
                f.api_state["image"]["RepoTags"] = value
                record = f.run()
                self.assertEqual(record["facts"]["drift"], {"repo_tags": [value, [f.pins.provider]]})

    def test_unreachable_desktop_api_is_labelled_as_desktop(self):
        f = self.fixture()

        def down(path, timeout):
            raise ConnectionRefusedError("no desktop")

        f.desktop_api_get = down
        self.refused_before_writes(f, "desktop_api_unavailable")

    def test_unreachable_native_api_is_a_refusal(self):
        f = self.fixture()

        def down(path, timeout):
            raise ConnectionRefusedError("no daemon")

        f.api_get = down
        self.refused_before_writes(f, "native_api_unavailable")

    def test_not_root_is_refused(self):
        f = self.fixture(require_root=True)
        if os.geteuid() == 0:
            original = b1.os.geteuid
            b1.os.geteuid = lambda: 1001
            self.addCleanup(setattr, b1.os, "geteuid", original)
        self.refused_before_writes(f, "not_root")

    def test_existing_archive_or_symlinked_directory_is_never_overwritten(self):
        f = self.fixture()
        Path(f.pins.archive_dir).mkdir()
        f.target.write_bytes(b"earlier")
        record = f.run()
        self.assertEqual(record["cause"], "archive_dir_not_empty")
        self.assertEqual(f.target.read_bytes(), b"earlier")
        self.assertEqual(f.saves(), [])
        g = self.fixture()
        os.symlink(g.tmp / "elsewhere", g.pins.archive_dir)
        self.assertEqual(g.run()["cause"], "archive_dir_symlink")
        self.assertEqual(g.saves(), [])

    def test_save_over_the_ceiling_stops_and_retains_the_partial_archive(self):
        f = self.fixture()
        f.state["save_pad"] = 2 * 1024 * 1024
        f.save()
        record = f.run()
        self.assertEqual(record["cause"], "archive_ceiling", record)
        self.assertLessEqual(f.target.stat().st_size, f.pins.archive_ceiling)
        self.assertTrue(f.target.exists())
        self.assertEqual(f.imports(), [])

    def test_failed_save_is_retained_and_not_imported(self):
        f = self.fixture()
        f.state["save_rc"] = 1
        f.save()
        record = f.run()
        self.assertEqual(record["cause"], "save_failed")
        self.assertTrue(f.target.exists())
        self.assertEqual(f.imports(), [])

    def test_deadline_during_save_kills_the_exporter(self):
        f = self.fixture(deadline_seconds=2.0)
        f.state["save_sleep"] = 30
        f.save()
        start = time.monotonic()
        record = f.run()
        self.assertEqual(record["cause"], "deadline", record)
        self.assertLess(time.monotonic() - start, 10)
        self.assertEqual(f.imports(), [])
        out = subprocess.run(["pgrep", "-f", str(f.docker)], capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "")  # the exporter was killed, not left running

    def membership(self, cause, **archive_kw):
        f = self.fixture()
        write_archive(f.archive, f.img, **archive_kw)
        record = f.run()
        self.assertEqual((record["outcome"], record["cause"]), ("refused", cause), record)
        self.assertEqual(f.imports(), [])
        self.assertTrue(f.target.exists())  # retained for inspection
        return record

    def test_membership_refusals_precede_any_import(self):
        img = build_image()
        layer0 = "blobs/sha256/" + digest(img["layers"][0])[7:]
        self.membership("archive_unexpected_member", extra=[("repositories", b"{}")])
        self.membership("archive_unexpected_member", extra=[("blobs/sha256/" + "e" * 64 + "/x", b"")])
        self.membership("archive_member_type", symlink="blobs/sha256/" + "f" * 64)
        self.membership("archive_blob_hash", corrupt=b"Z" * 1000)
        self.membership("archive_duplicate_member", duplicate=layer0)
        self.membership("archive_oci_layout", layout=b'{"imageLayoutVersion":"2.0.0"}')

    def test_extra_well_named_blob_is_refused(self):
        stray = b"stray"
        record = self.membership("archive_blob_set", extra=[("blobs/sha256/" + digest(stray)[7:], stray)])
        self.assertEqual(record["facts"]["extra"], [digest(stray)])

    def test_missing_layer_is_refused(self):
        img = build_image()
        record = self.membership("archive_blob_set", drop=("blobs/sha256/" + digest(img["layers"][2])[7:],))
        self.assertEqual(record["facts"]["missing"], [digest(img["layers"][2])])

    def test_index_child_must_be_the_unchanged_provider_index(self):
        img = build_image()
        self.membership("archive_index_child", child={"mediaType": OCI_INDEX, "digest": digest(img["manifest"]),
                                                      "size": len(img["manifest"])})
        self.membership("archive_index_child", child={"mediaType": "application/vnd.oci.image.manifest.v1+json",
                                                      "digest": digest(img["index"]), "size": len(img["index"])})

    def test_legacy_manifest_must_be_anonymous_and_match_the_layers(self):
        img = build_image()
        good_layers = ["blobs/sha256/" + digest(x)[7:] for x in img["layers"]]
        config = "blobs/sha256/" + digest(img["config"])[7:]
        self.membership("archive_legacy_manifest",
                        legacy=[{"Config": config, "RepoTags": None, "Layers": list(reversed(good_layers))}])
        self.membership("archive_legacy_manifest",
                        legacy=[{"Config": config, "RepoTags": ["example.test/base:latest"], "Layers": good_layers}])

    def test_pinned_counts_and_sizes_are_enforced(self):
        f = self.fixture(content_bytes=1)
        self.assertEqual(f.run()["cause"], "archive_content_bytes")
        g = self.fixture(layer_count=2)
        self.assertEqual(g.run()["cause"], "archive_manifest")
        h = self.fixture(config_size=1)
        self.assertEqual(h.run()["cause"], "archive_manifest")
        for fx in (f, g, h):
            self.assertEqual(fx.imports(), [])

    def test_provider_index_must_name_the_amd64_platform_manifest(self):
        f = self.fixture(img=build_image(platform="arm64"))
        self.assertEqual(f.run()["cause"], "archive_provider_index")
        self.assertEqual(f.imports(), [])

    def test_config_must_be_linux_amd64(self):
        f = self.fixture(img=build_image(config_arch="arm64"))
        self.assertEqual(f.run()["cause"], "archive_config")
        self.assertEqual(f.imports(), [])

    def test_oversized_metadata_member_is_refused(self):
        img = build_image()
        legacy = [{"Config": "blobs/sha256/" + digest(img["config"])[7:], "RepoTags": None,
                   "Layers": ["blobs/sha256/" + digest(x)[7:] for x in img["layers"]], "Pad": "p" * (70 * 1024)}]
        self.membership("archive_metadata_too_large", legacy=legacy)

    def test_member_count_is_capped_before_names_are_judged(self):
        strays = [b"s%d" % i for i in range(60)]
        self.membership("archive_too_many_members", extra=[("blobs/sha256/" + digest(x)[7:], x) for x in strays])

    def test_truncated_reference_listing_is_not_trusted(self):
        f = self.fixture()
        f.state["refs"] = ["example.test/filler:%07d" % i for i in range(60000)] + [f.pins.provider]
        f.save()
        self.refused_before_writes(f, "containerd_unreachable")

    def test_archive_directory_must_be_root_owned_and_not_group_writable(self):
        f = self.fixture(require_root=True)
        original = b1.os.geteuid
        b1.os.geteuid = lambda: 0
        self.addCleanup(setattr, b1.os, "geteuid", original)
        Path(f.pins.archive_dir).mkdir()
        os.chmod(f.pins.archive_dir, 0o777)
        record = f.run()
        self.assertEqual(record["cause"], "archive_dir_ownership")
        self.assertEqual(f.saves(), [])

    def test_missing_reference_after_import_is_a_refusal(self):
        f = self.fixture()
        f.state["import_no_ref"] = True
        f.save()
        self.assertEqual(f.run()["cause"], "native_reference_missing_after_import")

    def test_available_attestation_on_desktop_is_refused_before_the_save(self):
        f = self.fixture()
        f.api_state["desktop_manifests"].append({"ID": "sha256:" + "8" * 64, "Kind": "attestation", "Available": True})
        record = self.refused_before_writes(f, "desktop_extra_content")
        self.assertEqual(len(record["facts"]["available"]), 2)

    def test_named_index_child_is_refused_before_import(self):
        img = build_image()
        record = self.membership("archive_index_annotations", child={
            "mediaType": OCI_INDEX, "digest": digest(img["index"]), "size": len(img["index"]),
            "annotations": {"containerd.io/distribution.source.example.test": "base",
                            "io.containerd.image.name": "example.test/other:latest"}})
        self.assertIn("io.containerd.image.name", record["facts"]["annotations"])

    def test_extra_native_reference_after_import_is_refused(self):
        f = self.fixture()
        f.state["refs"] = ["example.test/kept:1"]
        f.state["import_extra_ref"] = "example.test/other:latest"
        f.save()
        record = f.run()
        self.assertEqual(record["cause"], "native_references_changed")
        self.assertEqual(record["native_references_before"], ["example.test/kept:1"])

    def test_verification_honours_the_absolute_deadline(self):
        f = self.fixture()
        with open(f.archive, "rb") as handle:
            with self.assertRaises(b1.B1Refusal) as caught:
                b1.verify_archive(handle.fileno(), f.pins, deadline=time.monotonic() - 1)
        self.assertEqual(caught.exception.cause, "deadline")

    def test_trailing_bytes_after_the_archive_end_are_bounded(self):
        f = self.fixture()
        with open(f.archive, "ab") as handle:
            handle.write(b"\0" * (2 * 1024 * 1024))
        with open(f.archive, "rb") as handle:
            with self.assertRaises(b1.B1Refusal) as caught:
                b1.verify_archive(handle.fileno(), dataclasses.replace(f.pins, archive_ceiling=8 * 1024 * 1024))
        self.assertEqual(caught.exception.cause, "archive_trailing_data")

    def test_missing_compatibility_manifest_is_refused(self):
        self.membership("archive_legacy_manifest", no_legacy=True)

    def test_chain_id_follows_the_oci_definition(self):
        a, b, c = ("sha256:" + x * 64 for x in "abc")
        ab = "sha256:" + hashlib.sha256(f"{a} {b}".encode()).hexdigest()
        self.assertEqual(b1.chain_id([a]), a)
        self.assertEqual(b1.chain_id([a, b, c]), "sha256:" + hashlib.sha256(f"{ab} {c}".encode()).hexdigest())
        self.assertIsNone(b1.chain_id([]))
        self.assertIsNone(b1.chain_id(None))

    def test_successful_restore_does_not_mark_the_native_state_unknown(self):
        record = self.fixture().run()
        self.assertTrue(record["import_started"])
        self.assertNotIn("native_state", record)

    def test_failed_import_is_retained_without_retry(self):
        f = self.fixture()
        f.state["import_rc"] = 1
        f.save()
        record = f.run()
        self.assertEqual(record["cause"], "import_failed")
        self.assertIn("unknown", record["native_state"])  # a failed import never claims a clean native store
        self.assertEqual(len(f.imports()), 1)
        self.assertTrue(f.target.exists())

    def test_archive_replaced_after_verification_is_not_imported(self):
        f = self.fixture()
        original = b1.Restore.verify

        def verify_then_swap(self, fd):
            identity = original(self, fd)
            os.replace(f.archive, f.target)  # a different inode at the verified path
            return identity

        b1.Restore.verify = verify_then_swap
        self.addCleanup(setattr, b1.Restore, "verify", original)
        record = f.run()
        self.assertEqual(record["cause"], "archive_changed_before_import")
        self.assertEqual(f.imports(), [])

    def test_archive_changed_during_import_is_a_refusal(self):
        f = self.fixture()
        f.state["import_mutates_archive"] = True
        f.save()
        self.assertEqual(f.run()["cause"], "archive_changed_during_import")

    def test_post_import_drift_is_refused(self):
        cases = {
            "size": lambda img: img.update(Size=img["Size"] + 1),
            "repo_digests": lambda img: img.update(RepoDigests=img["RepoDigests"] + ["example.test/base@sha256:" + "1" * 64]),
            "rootfs_sha256,chain_id": lambda img: img["RootFS"]["Layers"].reverse(),
            "env_keys_sha256": lambda img: img["Config"]["Env"].append("EXTRA=1"),
            "unpacked_bytes": lambda img: img["Manifests"][0]["ImageData"]["Size"].update(Unpacked=4243),
            "id": lambda img: img.update(Id="sha256:" + "2" * 64),
            "repo_tags": lambda img: img.update(RepoTags=img["RepoTags"] + ["example.test/base:latest"]),
        }
        for key, mutate in cases.items():
            with self.subTest(key=key):
                f = self.fixture()
                mutate(f.api_state["image"])
                record = f.run()
                self.assertEqual(record["cause"], "post_import_drift", record)
                self.assertEqual(sorted(record["facts"]["drift"]), sorted(key.split(",")))
                self.assertTrue(f.target.exists())

    def test_unavailable_platform_manifest_is_drift(self):
        f = self.fixture()
        f.api_state["image"]["Manifests"][0]["Available"] = False
        record = f.run()
        self.assertEqual(record["facts"]["drift"], {"unpacked_bytes": [None, 4242]})

    def test_native_container_set_must_be_unchanged(self):
        f = self.fixture()
        f.api_state["containers_after"] = [{"Id": "c" * 64, "State": "exited"}, {"Id": "d" * 64, "State": "created"}]
        self.assertEqual(f.run()["cause"], "native_containers_changed")

    def test_unexpected_exception_is_recorded_not_raised(self):
        f = self.fixture()
        original = b1.verify_archive
        b1.verify_archive = lambda *args, **kwargs: (_ for _ in ()).throw(MemoryError("boom"))
        self.addCleanup(setattr, b1, "verify_archive", original)
        record = f.run()
        self.assertEqual((record["cause"], record["facts"]), ("internal_error", {"error": "MemoryError: boom"}))
        self.assertEqual(f.imports(), [])


class ReuseTests(unittest.TestCase):
    """A later attempt reusing the retained archive of a consumed one."""

    def fixture(self, archive_bytes=None, **kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        f = Fixture(Path(tmp.name), None, **kw)
        Path(f.pins.archive_dir).mkdir(mode=0o700)
        data = f.archive.read_bytes() if archive_bytes is None else archive_bytes
        f.target.write_bytes(data)
        f.retained = (hashlib.sha256(data).hexdigest(), len(data))
        return f

    def test_reuse_skips_only_the_save_and_restores(self):
        f = self.fixture()
        f.state.update(ingests="REF\tSIZE\tAGE\ntar-blobs/sha256/" + "0" * 64 + "\t339.7MB\t1 day",
                       leases="ID CREATED AT LABELS\n124685930-FsqA 2026-11-05 gc.expire=2026-11-06")
        f.save()
        before = f.target.read_bytes()
        record = f.run(reuse=f.retained)
        self.assertEqual(record["outcome"], "restored", record)
        self.assertEqual(record["mode"], "reuse")
        self.assertEqual(f.saves(), [])  # Desktop was not asked to save again
        self.assertEqual(len(f.imports()), 1)
        self.assertEqual(f.target.read_bytes(), before)  # read-only: untouched
        self.assertEqual(record["archive"]["sha256"], f.retained[0])
        self.assertEqual([st["stage"] for st in record["stages"]],
                         ["preflight", "archive_reused", "verified", "imported", "native_verified"])
        for key in ("remnants_preflight", "remnants_before_import"):
            self.assertEqual(record[key]["leases"][1], "124685930-FsqA 2026-11-05 gc.expire=2026-11-06")
            self.assertIn("339.7MB", record[key]["ingests"][1])

    def test_recorded_sha256_must_match_after_full_verification(self):
        f = self.fixture()
        record = f.run(reuse=("f" * 64, f.retained[1]))
        self.assertEqual(record["cause"], "reuse_archive_sha256")
        self.assertEqual(record["facts"]["observed"], f.retained[0])
        self.assertEqual(f.imports(), [])

    def test_recorded_size_must_match_before_anything_is_read(self):
        f = self.fixture()
        record = f.run(reuse=(f.retained[0], f.retained[1] + 1))
        self.assertEqual(record["cause"], "reuse_archive_size")
        self.assertNotIn("archive", record)
        self.assertEqual(f.imports(), [])

    def test_matching_sha256_never_replaces_membership_verification(self):
        img = build_image()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bad = Path(tmp.name, "bad.tar")
        write_archive(bad, img, extra=[("repositories", b"{}")])
        f = self.fixture(archive_bytes=bad.read_bytes())
        record = f.run(reuse=f.retained)  # the caller's sha256 is right for these bytes
        self.assertEqual(record["cause"], "archive_unexpected_member")
        self.assertEqual(f.imports(), [])

    def test_archive_directory_must_hold_exactly_the_archive(self):
        f = self.fixture()
        Path(f.pins.archive_dir, "stray").write_bytes(b"x")
        self.assertEqual(f.run(reuse=f.retained)["cause"], "reuse_archive_dir_contents")
        g_ = self.fixture()
        g_.target.unlink()
        self.assertEqual(g_.run(reuse=g_.retained)["cause"], "reuse_archive_dir_contents")
        for fx in (f, g_):
            self.assertEqual(fx.imports(), [])

    def test_symlinked_archive_or_missing_directory_is_refused(self):
        f = self.fixture()
        f.target.unlink()
        os.symlink(f.archive, f.target)
        self.assertEqual(f.run(reuse=f.retained)["cause"], "reuse_archive_unreadable")
        g_ = self.fixture()
        g_.target.unlink()
        os.rmdir(g_.pins.archive_dir)
        self.assertEqual(g_.run(reuse=g_.retained)["cause"], "reuse_archive_dir_unusable")
        for fx in (f, g_):
            self.assertEqual(fx.imports(), [])

    def test_reused_directory_must_be_root_owned_real_and_not_group_writable(self):
        f = self.fixture(require_root=True)
        original = b1.os.geteuid
        b1.os.geteuid = lambda: 0
        self.addCleanup(setattr, b1.os, "geteuid", original)
        os.chmod(f.pins.archive_dir, 0o777)
        self.assertEqual(f.run(reuse=f.retained)["cause"], "archive_dir_ownership")
        g_ = self.fixture()
        real = Path(g_.tmp, "real-b1")
        os.rename(g_.pins.archive_dir, real)
        os.symlink(real, g_.pins.archive_dir)
        self.assertEqual(g_.run(reuse=g_.retained)["cause"], "archive_dir_symlink")
        for fx in (f, g_):
            self.assertEqual(fx.imports(), [])

    def test_planted_fifo_cannot_block_and_is_refused(self):
        f = self.fixture()
        f.target.unlink()
        os.mkfifo(f.target)
        result: dict = {}
        worker = threading.Thread(target=lambda: result.update(f.run(reuse=f.retained)), daemon=True)
        worker.start()
        worker.join(20)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result["cause"], "reuse_archive_not_regular")
        self.assertEqual(f.imports(), [])

    def test_reused_file_must_be_single_linked_and_not_group_writable(self):
        f = self.fixture()
        os.link(f.target, Path(f.tmp, "second-name"))
        self.assertEqual(f.run(reuse=f.retained)["cause"], "reuse_archive_ownership")
        g_ = self.fixture()
        os.chmod(g_.target, 0o666)
        self.assertEqual(g_.run(reuse=g_.retained)["cause"], "reuse_archive_ownership")
        for fx in (f, g_):
            self.assertEqual(fx.imports(), [])

    def test_owner_uid_is_checked_for_the_directory_and_the_file(self):
        real_fstat = b1.os.fstat
        original_euid = b1.os.geteuid
        b1.os.geteuid = lambda: 0
        self.addCleanup(setattr, b1.os, "geteuid", original_euid)
        for target in ("dir", "file"):
            with self.subTest(target=target):
                f = self.fixture(require_root=True)
                os.chmod(f.pins.archive_dir, 0o700)

                def fake_fstat(fd, target=target):
                    st = real_fstat(fd)
                    is_dir = stat.S_ISDIR(st.st_mode)
                    if (target == "dir") == is_dir:
                        fields = list(st)
                        fields[4] = 1000  # st_uid: not root, while the mode stays acceptable
                        return os.stat_result(fields)
                    fields = list(st)
                    fields[4] = 0
                    return os.stat_result(fields)

                b1.os.fstat = fake_fstat
                try:
                    record = f.run(reuse=f.retained)
                finally:
                    b1.os.fstat = real_fstat
                self.assertEqual(record["cause"], "archive_dir_ownership" if target == "dir" else "reuse_archive_ownership")
                self.assertEqual(f.imports(), [])

    def test_long_remnant_listings_are_marked_truncated(self):
        f = self.fixture()
        f.state["leases"] = "ID CREATED AT LABELS\n" + "\n".join(f"lease-{i}" for i in range(100))
        f.save()
        record = f.run(reuse=f.retained)
        self.assertEqual(len(record["remnants_preflight"]["leases"]), 64)
        self.assertTrue(record["remnants_preflight"]["leases_truncated"])
        self.assertFalse(record["remnants_preflight"]["ingests_truncated"])

    def test_reuse_keeps_the_preflight_refusals(self):
        f = self.fixture()
        f.api_state["image_present"] = True
        record = f.run(reuse=f.retained)
        self.assertEqual(record["cause"], "native_image_present")
        self.assertEqual(f.imports(), [])

    def test_reuse_keeps_the_post_import_contract(self):
        f = self.fixture()
        f.api_state["image"]["Size"] += 1
        record = f.run(reuse=f.retained)
        self.assertEqual(record["cause"], "post_import_drift")
        self.assertIn("unknown", record["native_state"])

    def test_save_mode_also_records_remnants(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        f = Fixture(Path(tmp.name), None)
        record = f.run()
        self.assertEqual((record["outcome"], record["mode"]), ("restored", "save"))
        self.assertIn("remnants_preflight", record)
        self.assertIn("remnants_before_import", record)


class RunnerTests(unittest.TestCase):
    def test_capture_is_bounded_and_overflow_reported(self):
        done = b1.run_bounded([sys.executable, "-c", "import sys; sys.stdout.write('x' * (3 * 1024 * 1024))"],
                              time.monotonic() + 30)
        self.assertEqual(done.rc, 0)
        self.assertEqual(len(done.stdout), b1.CHANNEL_LIMIT)
        self.assertTrue(done.stdout_overflow)

    def test_small_output_is_not_overflow(self):
        done = b1.run_bounded([sys.executable, "-c", "print('ok')"], time.monotonic() + 30)
        self.assertEqual((done.rc, done.stdout, done.stdout_overflow), (0, b"ok\n", False))

    def test_expired_deadline_starts_nothing(self):
        done = b1.run_bounded([sys.executable, "-c", "raise SystemExit(5)"], time.monotonic() - 1)
        self.assertTrue(done.timed_out)
        self.assertIsNone(done.rc)

    def test_write_error_is_reported_separately_from_the_ceiling(self):
        r, w = os.pipe()
        os.close(r)  # writes fail with EPIPE
        old = signal.signal(signal.SIGPIPE, signal.SIG_IGN)
        try:
            done = b1.run_bounded([sys.executable, "-c", "import sys; sys.stdout.write('x' * 100000)"],
                                  time.monotonic() + 30, out_fd=w, ceiling=10 ** 9)
        finally:
            signal.signal(signal.SIGPIPE, old)
            os.close(w)
        self.assertFalse(done.ceiling_exceeded)
        self.assertIn("BrokenPipeError", done.write_error)

    def test_returns_only_after_the_last_bytes_reach_a_slow_sink(self):
        # the exporter exits at once, but its output drains into the sink slower than the kill grace
        r, w = os.pipe()
        drained = bytearray()

        def slow_reader():
            time.sleep(b1.KILL_GRACE_SECONDS + 2)
            while chunk := os.read(r, 65536):
                drained.extend(chunk)

        reader = threading.Thread(target=slow_reader, daemon=True)
        reader.start()
        try:
            done = b1.run_bounded([sys.executable, "-c", "import sys; sys.stdout.write('x' * 300000)"],
                                  time.monotonic() + 30, out_fd=w, ceiling=10 ** 9)
        finally:
            os.close(w)
            reader.join(10)
            os.close(r)
        self.assertEqual((done.rc, done.timed_out, done.written), (0, False, 300000))
        self.assertEqual(len(drained), 300000)


class UnixApiTests(unittest.TestCase):
    def test_get_over_a_unix_socket(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"path": self.path}).encode() if self.path != "/missing" else b'{"message":"x"}'
                self.send_response(200 if self.path != "/missing" else 404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

            def address_string(self):
                return "unix"

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "api.sock")
            server = socketserver.UnixStreamServer(path, Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                self.assertEqual(b1.unix_api_get(path, "/v1.55/info", 5), (200, {"path": "/v1.55/info"}))
                self.assertEqual(b1.unix_api_get(path, "/missing", 5), (404, {"message": "x"}))
                with self.assertRaises(b1.B1Refusal):
                    b1.unix_api_get(path, "/v1.55/info", 5, limit=4)
            finally:
                server.shutdown()
                server.server_close()


DRIVER = r'''
import json, sys
sys.path.insert(0, {scripts!r}); sys.path.insert(0, {tests!r})
import accepted_policy_b1_restore_v1 as b1
import test_accepted_policy_b1_restore_v1 as t
from pathlib import Path
f = t.Fixture.__new__(t.Fixture)
f.state_path = Path({state!r}); f.api_state = json.loads(Path({api!r}).read_text())
f.pins = b1.Pins(**json.loads(Path({pins!r}).read_text()))
sys.exit(b1.main(sys.argv[1:], pins=f.pins, api_get=f.api_get, desktop_api_get=f.desktop_api_get))
'''


class CliTests(unittest.TestCase):
    def driver(self, f: Fixture, record: Path, extra=()) -> subprocess.Popen:
        pins_file, api_file, driver = f.tmp / "pins.json", f.tmp / "api.json", f.tmp / "driver.py"
        pins_file.write_text(json.dumps(dataclasses.asdict(f.pins)))
        api_file.write_text(json.dumps(f.api_state))
        driver.write_text(DRIVER.format(scripts=str(ROOT / "scripts"), tests=str(ROOT / "tests"),
                                        state=str(f.state_path), api=str(api_file), pins=str(pins_file)))
        env = dict(os.environ, B1_FAKE_STATE=str(f.state_path))
        return subprocess.Popen([sys.executable, str(driver), "--record", str(record), *extra], env=env)

    def test_main_writes_the_record_once_and_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(Path(tmp))
            record = Path(tmp, "b1.json")
            self.assertEqual(self.driver(f, record).wait(60), 0)
            self.assertEqual(json.loads(record.read_text())["outcome"], "restored")
            self.assertEqual(self.driver(f, record).wait(60), 2)  # an existing record is refused, not overwritten
            self.assertEqual(json.loads(record.read_text())["outcome"], "restored")

    def test_reuse_arguments_are_validated_and_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(Path(tmp))
            record = Path(tmp, "b1.json")
            for extra in (["--reuse-archive-sha256", "a" * 64], ["--reuse-archive-size", "10"],
                          ["--reuse-archive-sha256", "A" * 64, "--reuse-archive-size", "10"],
                          ["--reuse-archive-sha256", "a" * 64, "--reuse-archive-size", "0"],
                          ["--reuse-archive-sha256", "a" * 64,
                           "--reuse-archive-size", str(f.pins.archive_ceiling + 1)]):
                with self.subTest(extra=extra):
                    self.assertEqual(self.driver(f, record, extra).wait(60), 2)
                    self.assertFalse(record.exists())
            Path(f.pins.archive_dir).mkdir(mode=0o700)
            data = f.archive.read_bytes()
            f.target.write_bytes(data)
            extra = ["--reuse-archive-sha256", hashlib.sha256(data).hexdigest(), "--reuse-archive-size", str(len(data))]
            self.assertEqual(self.driver(f, record, extra).wait(60), 0)
            written = json.loads(record.read_text())
            self.assertEqual((written["outcome"], written["mode"]), ("restored", "reuse"))
            self.assertEqual(f.saves(), [])

    def test_refusal_returns_three_with_the_cause_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(Path(tmp))
            f.api_state["image_present"] = True
            record = Path(tmp, "b1.json")
            self.assertEqual(self.driver(f, record).wait(60), 3)
            self.assertEqual(json.loads(record.read_text())["cause"], "native_image_present")

    def test_sigterm_during_save_stops_the_exporter_and_still_writes_the_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(Path(tmp))
            f.state["save_sleep"] = 60
            f.save()
            record = Path(tmp, "b1.json")
            proc = self.driver(f, record)
            try:
                end = time.monotonic() + 20
                while not f.saves() and time.monotonic() < end:
                    time.sleep(0.05)
                time.sleep(0.2)
                proc.send_signal(signal.SIGTERM)
                rc = proc.wait(30)
            finally:
                if proc.poll() is None:
                    proc.kill()
            data = json.loads(record.read_text())
            self.assertEqual(rc, 3)
            self.assertEqual((data["cause"], data["facts"]), ("interrupted", {"signal": "SIGTERM"}))
            self.assertEqual(f.imports(), [])
            out = subprocess.run(["pgrep", "-f", str(f.docker)], capture_output=True, text=True)
            self.assertEqual(out.stdout.strip(), "")  # the exporter did not outlive the restore

    def test_production_pins_match_the_reviewed_b1_route(self):
        p = b1.PRODUCTION
        probe = (ROOT / "tests/fixtures/accepted_policy_fixture_compiler_probe_v1.py").read_text(encoding="utf-8")
        compiler = (ROOT / "tests/fixtures/accepted_policy_fixture_compiler_v1.py").read_text(encoding="utf-8")

        def pinned(text, key):
            return re.search(rf'^\s*"?{key}"?\s*[:=]\s*"?([^",\n]+)"?', text, re.M).group(1)

        self.assertEqual(p.native_engine_id, pinned(probe, "engine_id"))
        self.assertEqual(p.native_version, pinned(probe, "server_version"))
        self.assertEqual(p.native_size, int(pinned(probe, "provider_size")))
        self.assertEqual(p.rootfs_sha256, pinned(probe, "rootfs_sha256"))
        self.assertEqual(p.env_keys_sha256, pinned(probe, "env_keys_sha256"))
        self.assertEqual(p.unpacked_bytes, int(pinned(probe, "unpacked_bytes")))
        self.assertEqual(p.chain_id, pinned(probe, "chain_id"))
        self.assertEqual(p.provider, pinned(compiler, "PROVIDER"))
        self.assertEqual(p.provider_id, pinned(compiler, "PROVIDER_ID"))
        self.assertEqual(p.config_digest, pinned(compiler, "PROVIDER_CONFIG_DIGEST"))
        self.assertEqual(p.manifest_digest, pinned(compiler, "PROVIDER_PLATFORM_MANIFEST"))
        self.assertEqual((p.desktop_host, p.desktop_engine_id, p.desktop_version),
                         ("unix:///run/vast-pr9-desktop-api.sock", "aa8f3d33-e1dc-4ed2-ad06-488b46b332d0", "29.8.2"))
        self.assertEqual((p.containerd_address, p.base_name, p.deadline_seconds, p.docker, p.ctr),
                         ("/run/containerd/containerd.sock", "nvcr.io/nvidia/deepstream", 5400.0,
                          "/usr/bin/docker", "/usr/bin/ctr"))
        self.assertEqual(p.provider, "nvcr.io/nvidia/deepstream@" + p.provider_id)
        self.assertEqual((p.index_size, p.manifest_size, p.config_size, p.layer_count, p.blob_count),
                         (745, 10184, 47088, 47, 50))
        self.assertEqual(p.content_bytes, 10_469_524_887 + 47_088 + 10_184 + 745)
        self.assertEqual((p.native_size, p.unpacked_bytes), (10_469_582_904, 18_930_790_400))
        self.assertEqual((p.archive_dir, p.archive_ceiling), ("/var/lib/vast-pr9-b1", 10 * 1024 ** 3))
        self.assertEqual((p.containerd_version, p.containerd_revision, p.namespace),
                         ("v2.3.3", "aad11006b869517fcd3009450b6f82da282e1a9b", "moby"))
        self.assertTrue(p.require_root)


if __name__ == "__main__":
    unittest.main()
