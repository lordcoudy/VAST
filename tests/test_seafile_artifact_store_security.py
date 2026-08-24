from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from seafile_artifact_store import (  # noqa: E402
    ArtifactIntegrityError,
    ArtifactStoreError,
    SeafileArtifactStore,
    SeafileShareLinks,
    _SameOriginRedirectHandler,
)


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

    def _post_file(self, target: str, local_path: Path, remote_name: str) -> object:
        self._validate_remote_name(remote_name)
        self._validate_https_same_origin(target, label="upload target")
        self.fixture_opener.stored[remote_name] = local_path.read_bytes()
        return [{"name": remote_name, "size": local_path.stat().st_size}]


class SeafileArtifactStoreSecurityTests(unittest.TestCase):
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
