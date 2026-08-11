from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import unittest
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from seafile_artifact_store import (  # noqa: E402
    ArtifactIntegrityError,
    SeafileArtifactStore,
    SeafileShareLinks,
)


class SeafileFixtureHandler(BaseHTTPRequestHandler):
    stored: dict[str, bytes] = {}

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/v2.1/upload-links/uploadtoken/upload/":
            self._json(
                {
                    "upload_link": (
                        f"http://127.0.0.1:{self.server.server_port}"
                        "/seafhttp/upload-api/test"
                    )
                }
            )
            return
        if parsed.path == "/api/v2.1/share-links/readtoken/dirents/":
            self._json(
                {
                    "dirent_list": [
                        {
                            "file_name": name,
                            "file_path": f"/{name}",
                            "is_dir": False,
                            "size": len(payload),
                        }
                        for name, payload in self.stored.items()
                    ]
                }
            )
            return
        if parsed.path == "/d/readtoken/files/":
            query = parse_qs(parsed.query)
            if query.get("dl") != ["1"]:
                payload = b"<html>preview</html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            name = query.get("p", [""])[0].lstrip("/")
            payload = self.stored.get(name)
            if payload is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/seafhttp/upload-api/test":
            self.send_error(404)
            return
        length = int(self.headers["Content-Length"])
        body = self.rfile.read(length)
        message = BytesParser(policy=default).parsebytes(
            (
                f"Content-Type: {self.headers['Content-Type']}\r\n"
                "MIME-Version: 1.0\r\n\r\n"
            ).encode("ascii")
            + body
        )
        file_parts = [
            part
            for part in message.iter_parts()
            if part.get_param("name", header="content-disposition") == "file"
        ]
        if len(file_parts) != 1:
            self.send_error(400)
            return
        part = file_parts[0]
        name = part.get_filename()
        payload = part.get_payload(decode=True)
        self.stored[str(name)] = payload
        self._json([{"name": name, "size": len(payload), "id": "fixture-id"}])


class SeafileArtifactStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        SeafileFixtureHandler.stored = {}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), SeafileFixtureHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        base = f"http://127.0.0.1:{self.server.server_port}"
        links = SeafileShareLinks.from_urls(
            f"{base}/u/d/uploadtoken/",
            f"{base}/d/readtoken/",
        )
        self.store = SeafileArtifactStore(links, timeout_s=5)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_link_tokens_are_parsed_but_redacted_from_repr(self) -> None:
        representation = repr(self.store.links)
        self.assertNotIn("uploadtoken", representation)
        self.assertNotIn("readtoken", representation)
        self.assertIn("127.0.0.1", representation)

    def test_upload_is_verified_by_streamed_readback_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "pair.tar.zst"
            artifact.write_bytes((b"accepted-evidence\n" * 1024) + b"tail")
            expected = hashlib.sha256(artifact.read_bytes()).hexdigest()

            result = self.store.upload_and_verify(artifact, remote_name="pair-0001.tar.zst")

        self.assertEqual(result["status"], "uploaded_and_verified")
        self.assertEqual(result["sha256"], expected)
        self.assertEqual(result["size_bytes"], len(SeafileFixtureHandler.stored["pair-0001.tar.zst"]))
        self.assertNotIn("uploadtoken", json.dumps(result))
        self.assertNotIn("readtoken", json.dumps(result))

    def test_hash_mismatch_fails_closed(self) -> None:
        SeafileFixtureHandler.stored["pair.tar.zst"] = b"remote-bytes"
        with self.assertRaisesRegex(ArtifactIntegrityError, "SHA-256"):
            self.store.verify_remote(
                "pair.tar.zst",
                expected_sha256=hashlib.sha256(b"remote-bytez").hexdigest(),
                expected_size=len(b"remote-bytes"),
            )


if __name__ == "__main__":
    unittest.main()
