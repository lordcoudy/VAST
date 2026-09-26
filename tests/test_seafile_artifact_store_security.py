from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import seafile_artifact_store as artifact_store_module  # noqa: E402
from seafile_artifact_store import (  # noqa: E402
    ArtifactIntegrityError,
    ArtifactStoreError,
    SeafileArtifactStore,
    SeafileShareLinks,
    _SameOriginRedirectHandler,
    _build_parser,
    _production_links_from_file,
)


class SimulatedCrash(BaseException):
    pass


class FakeResponse(io.BytesIO):
    def __init__(self, payload: bytes, *, url: str, status: int = 200) -> None:
        super().__init__(payload)
        self.status = status
        self._url = url

    def geturl(self) -> str:
        return self._url

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class FakeOpener:
    def __init__(self) -> None:
        self.stored: dict[str, bytes] = {}
        self.failures_remaining = 0
        self.failure_message = "temporary transport error"
        self.final_url_override: str | None = None
        self.response_statuses: list[int] = []
        self.calls = 0

    def open(self, request: object, *, timeout: float) -> FakeResponse:
        del timeout
        self.calls += 1
        url = str(getattr(request, "full_url"))
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise OSError(self.failure_message.replace("{url}", url))
        parsed = urlsplit(url)
        if parsed.path == "/api/v2.1/upload-links/uploadtoken/upload/":
            payload = json.dumps(
                {"upload_link": "https://seafile.example/seafhttp/upload-api/test"}
            ).encode("utf-8")
        elif parsed.path == "/api/v2.1/share-links/readtoken/dirents/":
            payload = json.dumps(
                {
                    "dirent_list": [
                        {
                            "file_name": name,
                            "file_path": f"/{name}",
                            "is_dir": False,
                            "size": len(value),
                        }
                        for name, value in self.stored.items()
                    ]
                }
            ).encode("utf-8")
        elif parsed.path == "/d/readtoken/files/":
            name = parse_qs(parsed.query).get("p", [""])[0].lstrip("/")
            payload = self.stored[name]
        else:
            raise AssertionError(f"unexpected fake request path: {parsed.path}")
        status = self.response_statuses.pop(0) if self.response_statuses else 200
        return FakeResponse(payload, url=self.final_url_override or url, status=status)


class FixtureStore(SeafileArtifactStore):
    def __init__(self, opener: FakeOpener, **kwargs: object) -> None:
        links = SeafileShareLinks.from_urls(
            "https://seafile.example/u/d/uploadtoken/",
            "https://seafile.example/d/readtoken/",
        )
        super().__init__(links, opener=opener, timeout_s=5, **kwargs)
        self.fixture_opener = opener

    def _post_file(
        self,
        target: str,
        local_path: Path,
        remote_name: str,
        *,
        source_fd: int | None = None,
        source_size: int | None = None,
    ) -> object:
        self._validate_remote_name(remote_name)
        self._validate_https_same_origin(target, label="upload target")
        if source_fd is None:
            payload = local_path.read_bytes()
        else:
            duplicate = os.dup(source_fd)
            try:
                os.lseek(duplicate, 0, os.SEEK_SET)
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(duplicate, 8192)
                    if not chunk:
                        break
                    chunks.append(chunk)
                payload = b"".join(chunks)
            finally:
                os.close(duplicate)
        if source_size is not None and len(payload) != source_size:
            raise AssertionError("fixture held upload size drifted")
        self.fixture_opener.stored[remote_name] = payload
        return [{"name": remote_name, "size": len(payload)}]


class SeafileArtifactStoreSecurityTests(unittest.TestCase):
    def test_cli_exposes_link_file_and_explicit_live_preflight(self) -> None:
        arguments = _build_parser().parse_args(
            ["--links-file", "seafile.txt", "preflight", "--live-upload-readback"]
        )
        self.assertEqual(arguments.links_file, Path("seafile.txt"))
        self.assertIs(arguments.live_upload_readback, True)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            _build_parser().parse_args(["preflight"])
        with self.assertRaisesRegex(ArtifactStoreError, "seafile.txt"):
            _production_links_from_file(Path("links.txt"))

    def test_links_require_https_and_one_origin(self) -> None:
        with self.assertRaisesRegex(ArtifactStoreError, "HTTPS"):
            SeafileShareLinks.from_urls(
                "http://seafile.example/u/d/uploadtoken/",
                "http://seafile.example/d/readtoken/",
            )
        with self.assertRaisesRegex(ArtifactStoreError, "same origin"):
            SeafileShareLinks.from_urls(
                "https://upload.example/u/d/uploadtoken/",
                "https://read.example/d/readtoken/",
            )

    def test_link_file_accepts_labeled_direct_links_without_layout_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "seafile.txt"
            path.write_text(
                "download link - https://seafile.example/d/readtoken\n"
                "upload link - https://seafile.example/u/d/uploadtoken\n"
                "capacity - 1000 GB\n",
                encoding="utf-8",
            )

            links = SeafileShareLinks.from_file(path)

        self.assertEqual(links.base_url, "https://seafile.example")
        rendered = repr(links)
        self.assertNotIn("uploadtoken", rendered)
        self.assertNotIn("readtoken", rendered)

    def test_link_file_rejects_ambiguous_or_nonregular_input_without_echoing_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = {
                "missing.txt": "download link - https://seafile.example/d/readtoken\n",
                "extra.txt": (
                    "https://seafile.example/d/readtoken\n"
                    "https://seafile.example/u/d/uploadtoken\n"
                    "https://seafile.example/d/anothersecret\n"
                ),
            }
            for name, payload in cases.items():
                with self.subTest(name=name):
                    path = root / name
                    path.write_text(payload, encoding="utf-8")
                    with self.assertRaises(ArtifactStoreError) as raised:
                        SeafileShareLinks.from_file(path)
                    rendered = repr(raised.exception)
                    self.assertNotIn("readtoken", rendered)
                    self.assertNotIn("uploadtoken", rendered)
                    self.assertNotIn("anothersecret", rendered)
            target = root / "target.txt"
            target.write_text(
                "https://seafile.example/d/readtoken\n"
                "https://seafile.example/u/d/uploadtoken\n",
                encoding="utf-8",
            )
            link = root / "link.txt"
            try:
                link.symlink_to(target)
            except (NotImplementedError, OSError):
                return
            with self.assertRaisesRegex(ArtifactStoreError, "unsafe"):
                SeafileShareLinks.from_file(link)

    def test_upload_target_rejects_cross_origin_and_downgrade(self) -> None:
        class TargetStore(FixtureStore):
            def __init__(self, target: str) -> None:
                super().__init__(FakeOpener())
                self.target = target

            def _json_get(self, path: str) -> object:
                del path
                return {"upload_link": self.target}

        for target in (
            "https://attacker.example/upload",
            "http://seafile.example/upload",
        ):
            with self.subTest(target=target):
                with self.assertRaisesRegex(ArtifactStoreError, "upload target"):
                    TargetStore(target)._upload_target()

    def test_cross_origin_redirect_is_rejected(self) -> None:
        opener = FakeOpener()
        opener.final_url_override = "https://attacker.example/stolen"
        store = FixtureStore(opener, retry_delays_s=())
        with self.assertRaisesRegex(ArtifactStoreError, "redirect"):
            store.list_remote_files()

    def test_redirect_handler_blocks_cross_origin_before_follow(self) -> None:
        handler = _SameOriginRedirectHandler(("https", "seafile.example", 443))
        request = type("RequestFixture", (), {"full_url": "https://seafile.example/start"})()
        with self.assertRaisesRegex(ArtifactStoreError, "redirect"):
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "https://attacker.example/stolen",
            )

    def test_transport_errors_are_redacted_and_not_chained(self) -> None:
        opener = FakeOpener()
        opener.failures_remaining = 1
        opener.failure_message = "failed for {url}"
        store = FixtureStore(opener, retry_delays_s=())
        with self.assertRaises(ArtifactStoreError) as raised:
            store.list_remote_files()
        rendered = repr(raised.exception)
        self.assertNotIn("readtoken", rendered)
        self.assertNotIn("https://", rendered)
        self.assertIsNone(raised.exception.__cause__)

    def test_retry_schedule_is_configurable_and_exhaustive(self) -> None:
        opener = FakeOpener()
        opener.failures_remaining = 5
        delays: list[float] = []
        store = FixtureStore(
            opener,
            retry_delays_s=(5, 15, 45, 120, 300),
            sleep_fn=delays.append,
        )
        self.assertEqual(store.list_remote_files(), {})
        self.assertEqual(opener.calls, 6)
        self.assertEqual(delays, [5.0, 15.0, 45.0, 120.0, 300.0])

    def test_retryable_http_statuses_retry_but_client_errors_do_not(self) -> None:
        retrying = FakeOpener()
        retrying.response_statuses = [503, 429]
        delays: list[float] = []
        store = FixtureStore(
            retrying,
            retry_delays_s=(1, 2),
            sleep_fn=delays.append,
        )
        self.assertEqual(store.list_remote_files(), {})
        self.assertEqual(retrying.calls, 3)
        self.assertEqual(delays, [1.0, 2.0])

        client_error = FakeOpener()
        client_error.response_statuses = [400]
        with self.assertRaisesRegex(ArtifactStoreError, "HTTP 400"):
            FixtureStore(client_error, retry_delays_s=(1, 2)).list_remote_files()
        self.assertEqual(client_error.calls, 1)

    def test_upload_and_materialize_are_stream_verified_and_idempotent(self) -> None:
        opener = FakeOpener()
        store = FixtureStore(opener)
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "pair.tar.zst"
            artifact.write_bytes((b"accepted-evidence\n" * 1024) + b"tail")
            expected = hashlib.sha256(artifact.read_bytes()).hexdigest()
            uploaded = store.upload_and_verify(artifact, remote_name="pair-0001.tar.zst")
            destination = Path(tmp) / "restored" / artifact.name
            first = store.materialize_remote(
                "pair-0001.tar.zst",
                destination=destination,
                expected_sha256=expected,
                expected_size=artifact.stat().st_size,
            )
            second = store.materialize_remote(
                "pair-0001.tar.zst",
                destination=destination,
                expected_sha256=expected,
                expected_size=artifact.stat().st_size,
            )
            self.assertEqual(uploaded["status"], "uploaded_and_verified")
            self.assertEqual(first["status"], "materialized_and_verified")
            self.assertEqual(second["status"], "already_materialized_and_verified")
            self.assertEqual(destination.read_bytes(), artifact.read_bytes())

    def test_upload_rejects_post_digest_path_rebind_without_uploading(self) -> None:
        opener = FakeOpener()
        original = b"ledger-pinned-upload-source\n" * 257
        foreign = b"same-uid-path-replacement\n"
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "pair.tar.zst"
            moved = Path(tmp) / "held-original.tar.zst"
            artifact.write_bytes(original)

            def attack(step: str, path: Path) -> None:
                if step != "post_digest_pre_upload":
                    return
                path.rename(moved)
                path.write_bytes(foreign)

            with self.assertRaisesRegex(
                ArtifactStoreError, "rebound or mutated before upload"
            ):
                FixtureStore(
                    opener, upload_physical_fault=attack
                ).upload_and_verify(
                    artifact, remote_name="pair.tar.zst"
                )
            self.assertEqual(moved.read_bytes(), original)
            self.assertEqual(artifact.read_bytes(), foreign)
            self.assertEqual(opener.stored, {})

    def test_upload_rejects_post_digest_same_inode_mutation(self) -> None:
        opener = FakeOpener()
        original = b"ledger-pinned-upload-source\n" * 257
        foreign = b"X" * len(original)
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "pair.tar.zst"
            artifact.write_bytes(original)
            original_inode = artifact.stat().st_ino

            def attack(step: str, path: Path) -> None:
                if step != "post_digest_pre_upload":
                    return
                with path.open("r+b") as output:
                    output.write(foreign)
                    output.flush()
                    os.fsync(output.fileno())

            with self.assertRaisesRegex(
                ArtifactStoreError, "rebound or mutated before upload"
            ):
                FixtureStore(
                    opener, upload_physical_fault=attack
                ).upload_and_verify(
                    artifact, remote_name="pair.tar.zst"
                )
            self.assertEqual(artifact.stat().st_ino, original_inode)
            self.assertEqual(artifact.read_bytes(), foreign)
            self.assertEqual(opener.stored, {})

    def test_materialize_recovers_each_physical_crash_window_same_path(self) -> None:
        payload = (b"ledger-pinned-seafile-archive\n" * 257) + b"tail"
        expected = hashlib.sha256(payload).hexdigest()
        for crash_step in (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(crash_step=crash_step), tempfile.TemporaryDirectory() as tmp:
                opener = FakeOpener()
                opener.stored["pair.tar.zst"] = payload
                destination = Path(tmp) / "restored" / "pair.tar.zst"
                faulted = False

                def fault(step: str, path: Path) -> None:
                    nonlocal faulted
                    if step == crash_step and not faulted:
                        faulted = True
                        raise SimulatedCrash(str(path))

                with self.assertRaises(SimulatedCrash):
                    FixtureStore(
                        opener, materialize_physical_fault=fault
                    ).materialize_remote(
                        "pair.tar.zst",
                        destination=destination,
                        expected_sha256=expected,
                        expected_size=len(payload),
                    )
                published_inode = (
                    destination.stat().st_ino if destination.exists() else None
                )

                resumed = FixtureStore(opener).materialize_remote(
                    "pair.tar.zst",
                    destination=destination,
                    expected_sha256=expected,
                    expected_size=len(payload),
                )

                self.assertTrue(faulted)
                self.assertEqual(destination.read_bytes(), payload)
                self.assertEqual(
                    resumed["status"],
                    (
                        "already_materialized_and_verified"
                        if published_inode is not None
                        else "materialized_and_verified"
                    ),
                )
                if published_inode is not None:
                    self.assertEqual(destination.stat().st_ino, published_inode)
                self.assertEqual(destination.stat().st_nlink, 1)

    def test_materialize_hardlink_fallback_recovers_post_publish_crash(self) -> None:
        payload = b"drvfs-fallback-archive\n" * 129
        expected = hashlib.sha256(payload).hexdigest()
        opener = FakeOpener()
        opener.stored["pair.tar.zst"] = payload
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "pair.tar.zst"

            def crash(step: str, _path: Path) -> None:
                if step == "post_publish_pre_parent_fsync":
                    raise SimulatedCrash(step)

            with mock.patch.object(
                artifact_store_module,
                "_rename_noreplace_at",
                return_value=False,
            ), self.assertRaises(SimulatedCrash):
                FixtureStore(
                    opener, materialize_physical_fault=crash
                ).materialize_remote(
                    "pair.tar.zst",
                    destination=destination,
                    expected_sha256=expected,
                    expected_size=len(payload),
                )
            published_inode = destination.stat().st_ino
            self.assertEqual(destination.stat().st_nlink, 2)

            resumed = FixtureStore(opener).materialize_remote(
                "pair.tar.zst",
                destination=destination,
                expected_sha256=expected,
                expected_size=len(payload),
            )

            self.assertEqual(
                resumed["status"], "already_materialized_and_verified"
            )
            self.assertEqual(destination.stat().st_ino, published_inode)
            self.assertEqual(destination.stat().st_nlink, 1)
            self.assertEqual(destination.read_bytes(), payload)

    def test_materialize_rejects_same_uid_stage_unlink_rebind(self) -> None:
        payload = b"accepted-archive\n" * 257
        foreign = b"same-uid-foreign-stage\n"
        expected = hashlib.sha256(payload).hexdigest()
        opener = FakeOpener()
        opener.stored["pair.tar.zst"] = payload
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "pair.tar.zst"
            rebound_stage: Path | None = None

            def attack(step: str, path: Path) -> None:
                nonlocal rebound_stage
                if step != "post_fsync_pre_publish":
                    return
                rebound_stage = path
                path.unlink()
                path.write_bytes(foreign)

            with self.assertRaisesRegex(
                ArtifactIntegrityError, "rebound or mutated before publication"
            ):
                FixtureStore(
                    opener, materialize_physical_fault=attack
                ).materialize_remote(
                    "pair.tar.zst",
                    destination=destination,
                    expected_sha256=expected,
                    expected_size=len(payload),
                )
            assert rebound_stage is not None
            self.assertFalse(destination.exists())
            self.assertEqual(rebound_stage.read_bytes(), foreign)
            foreign_inode = rebound_stage.stat().st_ino
            with self.assertRaisesRegex(
                ArtifactIntegrityError, "stage is missing or rebound"
            ):
                FixtureStore(opener).materialize_remote(
                    "pair.tar.zst",
                    destination=destination,
                    expected_sha256=expected,
                    expected_size=len(payload),
                )
            self.assertEqual(rebound_stage.stat().st_ino, foreign_inode)
            self.assertEqual(rebound_stage.read_bytes(), foreign)

    def test_materialize_rejects_same_inode_mutation_after_digest(self) -> None:
        payload = b"accepted-archive\n" * 257
        foreign = b"X" * len(payload)
        expected = hashlib.sha256(payload).hexdigest()
        opener = FakeOpener()
        opener.stored["pair.tar.zst"] = payload
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "pair.tar.zst"
            attacked_stage: Path | None = None

            def attack(step: str, path: Path) -> None:
                nonlocal attacked_stage
                if step != "post_fsync_pre_publish":
                    return
                attacked_stage = path
                path.chmod(0o600)
                with path.open("r+b") as output:
                    output.write(foreign)
                    output.flush()
                    os.fsync(output.fileno())
                path.chmod(0o444)

            with self.assertRaisesRegex(
                ArtifactIntegrityError, "rebound or mutated before publication"
            ):
                FixtureStore(
                    opener, materialize_physical_fault=attack
                ).materialize_remote(
                    "pair.tar.zst",
                    destination=destination,
                    expected_sha256=expected,
                    expected_size=len(payload),
                )
            assert attacked_stage is not None
            self.assertFalse(destination.exists())
            self.assertEqual(attacked_stage.read_bytes(), foreign)

    def test_materialize_rejects_racing_foreign_final_after_publish(self) -> None:
        payload = b"accepted-archive\n" * 257
        foreign = b"same-uid-foreign-final\n"
        expected = hashlib.sha256(payload).hexdigest()
        opener = FakeOpener()
        opener.stored["pair.tar.zst"] = payload
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "pair.tar.zst"

            def attack(step: str, path: Path) -> None:
                if step != "post_publish_pre_parent_fsync":
                    return
                path.unlink()
                path.write_bytes(foreign)

            with self.assertRaisesRegex(
                ArtifactIntegrityError, "rebound after publish"
            ):
                FixtureStore(
                    opener, materialize_physical_fault=attack
                ).materialize_remote(
                    "pair.tar.zst",
                    destination=destination,
                    expected_sha256=expected,
                    expected_size=len(payload),
                )
            foreign_inode = destination.stat().st_ino
            with self.assertRaises(ArtifactIntegrityError):
                FixtureStore(opener).materialize_remote(
                    "pair.tar.zst",
                    destination=destination,
                    expected_sha256=expected,
                    expected_size=len(payload),
                )
            self.assertEqual(destination.stat().st_ino, foreign_inode)
            self.assertEqual(destination.read_bytes(), foreign)

    def test_materialize_no_replace_rejects_foreign_final_race(self) -> None:
        payload = b"accepted-archive\n" * 257
        foreign = b"foreign-winner-before-publication\n"
        expected = hashlib.sha256(payload).hexdigest()
        opener = FakeOpener()
        opener.stored["pair.tar.zst"] = payload
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "pair.tar.zst"

            def attack(step: str, _path: Path) -> None:
                if step == "post_fsync_pre_publish":
                    destination.write_bytes(foreign)

            with self.assertRaises(ArtifactIntegrityError):
                FixtureStore(
                    opener, materialize_physical_fault=attack
                ).materialize_remote(
                    "pair.tar.zst",
                    destination=destination,
                    expected_sha256=expected,
                    expected_size=len(payload),
                )
            foreign_inode = destination.stat().st_ino
            self.assertEqual(destination.read_bytes(), foreign)
            with self.assertRaises(ArtifactIntegrityError):
                FixtureStore(opener).materialize_remote(
                    "pair.tar.zst",
                    destination=destination,
                    expected_sha256=expected,
                    expected_size=len(payload),
                )
            self.assertEqual(destination.stat().st_ino, foreign_inode)
            self.assertEqual(destination.read_bytes(), foreign)

    def test_preflight_is_read_only_and_redacts_capability_tokens(self) -> None:
        opener = FakeOpener()
        opener.stored["existing.bin"] = b"existing"
        store = FixtureStore(opener)

        result = store.preflight()

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["origin"], "https://seafile.example")
        self.assertEqual(result["remote_file_count"], 1)
        self.assertEqual(result["remote_size_bytes"], len(b"existing"))
        rendered = json.dumps(result, sort_keys=True)
        self.assertNotIn("uploadtoken", rendered)
        self.assertNotIn("readtoken", rendered)
        self.assertEqual(set(opener.stored), {"existing.bin"})

    def test_live_preflight_uploads_and_stream_verifies_a_fresh_probe(self) -> None:
        opener = FakeOpener()
        store = FixtureStore(opener)

        result = store.preflight(live_upload_readback=True)

        self.assertEqual(
            result["upload_capability"], "verified_live_upload_readback"
        )
        self.assertEqual(result["remote_file_count"], 1)
        self.assertEqual(len(opener.stored), 1)
        name, payload = next(iter(opener.stored.items()))
        self.assertRegex(name, r"^vast-seafile-live-preflight-v1-[0-9a-f]{32}\.bin$")
        self.assertEqual(result["remote_size_bytes"], len(payload))
        rendered = json.dumps(result, sort_keys=True)
        self.assertNotIn("uploadtoken", rendered)
        self.assertNotIn("readtoken", rendered)

    def test_existing_remote_or_destination_collision_fails_closed(self) -> None:
        opener = FakeOpener()
        opener.stored["pair.tar.zst"] = b"remote-bytes"
        store = FixtureStore(opener)
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "pair.tar.zst"
            artifact.write_bytes(b"different-local-bytes")
            with self.assertRaises(ArtifactIntegrityError):
                store.upload_and_verify(artifact, remote_name=artifact.name)
            destination = Path(tmp) / "destination.tar.zst"
            destination.write_bytes(b"local-collision")
            with self.assertRaisesRegex(ArtifactIntegrityError, "destination"):
                store.materialize_remote(
                    "pair.tar.zst",
                    destination=destination,
                    expected_sha256=hashlib.sha256(b"remote-bytes").hexdigest(),
                    expected_size=len(b"remote-bytes"),
                )
            self.assertEqual(destination.read_bytes(), b"local-collision")


if __name__ == "__main__":
    unittest.main()
