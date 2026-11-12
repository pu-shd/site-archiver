"""Tests for optional WARC capture of the requests-based crawl.

These run real HTTP requests against a throwaway local server so warcio's
connection patching is exercised exactly as it is during a crawl.
"""
import gzip
import http.server
import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

import scraper
from warcio.archiveiterator import ArchiveIterator

SECRET = "s3cret-bypass-value"
SECRET_HEADER = "x-wdsoit-bot-bypass"

PAGES = {
    "/": ("text/html", b"<html><head><link rel='stylesheet' href='/style.css'></head>"
                       b"<body><h1>home</h1></body></html>"),
    "/style.css": ("text/css", b"body { color: black; }"),
}


class _Handler(http.server.BaseHTTPRequestHandler):
    seen_secret = []

    def do_GET(self):
        _Handler.seen_secret.append(self.headers.get(SECRET_HEADER))
        entry = PAGES.get(self.path)
        if entry is None:
            self.send_response(404)
            self.end_headers()
            return
        content_type, body = entry
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _read_records(path):
    """Return every record, raising if any block or payload digest is wrong."""
    records = []
    with open(path, "rb") as f:
        for rec in ArchiveIterator(f, check_digests="raise"):
            body = rec.content_stream().read()
            records.append((rec, body))
    return records


class _LocalServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _Handler.seen_secret = []
        self.temp_dir = tempfile.mkdtemp()
        scraper.crawl_delay = 0.0
        scraper._last_request_at = None
        scraper.headers = {SECRET_HEADER: SECRET, "User-Agent": "test-agent"}
        scraper.secret_header_names = {SECRET_HEADER}

    def tearDown(self):
        shutil.rmtree(self.temp_dir)
        scraper.headers = {}
        scraper.secret_header_names = set()


class TestWarcCapture(_LocalServerTest):
    def test_capture_records_request_and_response(self):
        warc = os.path.join(self.temp_dir, "crawl.warc.gz")
        with scraper.warc_capture(warc):
            res = scraper.polite_get(self.base + "/", headers=scraper.headers, timeout=5)
        self.assertEqual(res.status_code, 200)

        records = _read_records(warc)
        types = [r.rec_type for r, _ in records]
        self.assertIn("request", types)
        self.assertIn("response", types)
        response = next(body for r, body in records if r.rec_type == "response")
        self.assertIn(b"<h1>home</h1>", response)

    def test_streamed_downloads_are_recorded_in_full(self):
        warc = os.path.join(self.temp_dir, "crawl.warc.gz")
        with scraper.warc_capture(warc):
            res = scraper.polite_get(self.base + "/style.css", headers=scraper.headers, stream=True, timeout=5)
            b"".join(res.iter_content(chunk_size=4))
        bodies = [body for r, body in _read_records(warc) if r.rec_type == "response"]
        self.assertEqual(bodies, [b"body { color: black; }"])

    def test_secret_header_is_sent_but_never_written(self):
        warc = os.path.join(self.temp_dir, "crawl.warc.gz")
        with scraper.warc_capture(warc):
            scraper.polite_get(self.base + "/", headers=scraper.headers, timeout=5)

        # The origin must still receive the real value...
        self.assertEqual(_Handler.seen_secret, [SECRET])
        # ...but the archive must not contain it anywhere, compressed or not.
        with open(warc, "rb") as f:
            raw = f.read()
        self.assertNotIn(SECRET.encode(), raw)
        self.assertNotIn(SECRET.encode(), gzip.decompress(raw))

        requests_ = [r for r, _ in _read_records(warc) if r.rec_type == "request"]
        self.assertEqual(len(requests_), 1)
        self.assertEqual(requests_[0].http_headers.get_header(SECRET_HEADER), scraper.REDACTED)
        # Non-secret headers are preserved for provenance.
        self.assertEqual(requests_[0].http_headers.get_header("User-Agent"), "test-agent")

    def test_redaction_is_case_insensitive(self):
        scraper.headers = {"X-WDSoit-Bot-Bypass": SECRET}
        warc = os.path.join(self.temp_dir, "crawl.warc.gz")
        with scraper.warc_capture(warc):
            scraper.polite_get(self.base + "/", headers=scraper.headers, timeout=5)
        with open(warc, "rb") as f:
            self.assertNotIn(SECRET.encode(), gzip.decompress(f.read()))
        _read_records(warc)  # digests stay valid after redaction

    def test_disabled_capture_writes_nothing(self):
        before = set(os.listdir(self.temp_dir))
        with scraper.warc_capture(None):
            res = scraper.polite_get(self.base + "/", headers=scraper.headers, timeout=5)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(set(os.listdir(self.temp_dir)), before)


class TestMainWarcConfig(_LocalServerTest):
    def _run_main(self, **extra):
        out = os.path.join(self.temp_dir, "out")
        os.makedirs(out)
        config = {
            "url": self.base + "/",
            "output_dir": out,
            "delay": 0,
            "headers": {SECRET_HEADER: SECRET},
            "allowed_asset_domains": "",
        }
        config.update(extra)
        path = os.path.join(self.temp_dir, "config.json")
        with open(path, "w") as f:
            json.dump(config, f)
        scraper.crawled_pages = set()
        scraper.downloaded_assets = {}
        with patch("sys.argv", ["scraper.py", path]):
            scraper.main()
        return out

    def test_crawl_writes_mirror_and_redacted_warc(self):
        warc = os.path.join(self.temp_dir, "site.warc.gz")
        out = self._run_main(warc_path=warc)

        self.assertTrue(os.path.exists(os.path.join(out, "index.html")))
        self.assertTrue(os.path.exists(os.path.join(out, "style.css")))

        records = _read_records(warc)
        uris = {r.rec_headers.get_header("WARC-Target-URI") for r, _ in records if r.rec_type == "response"}
        self.assertEqual(uris, {self.base + "/", self.base + "/style.css"})
        with open(warc, "rb") as f:
            self.assertNotIn(SECRET.encode(), gzip.decompress(f.read()))
        self.assertTrue(_Handler.seen_secret)
        self.assertTrue(all(v == SECRET for v in _Handler.seen_secret))

    def test_crawl_without_warc_path_writes_no_warc(self):
        out = self._run_main()
        self.assertTrue(os.path.exists(os.path.join(out, "index.html")))
        found = [f for root, _, files in os.walk(self.temp_dir) for f in files if ".warc" in f]
        self.assertEqual(found, [])

    def test_unwritable_warc_path_fails_before_crawling(self):
        missing = os.path.join(self.temp_dir, "no-such-dir", "site.warc.gz")
        with self.assertRaises(SystemExit) as ctx:
            self._run_main(warc_path=missing)
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertEqual(_Handler.seen_secret, [], "no request should be made with a bad warc_path")

    def test_existing_warc_is_not_overwritten(self):
        warc = os.path.join(self.temp_dir, "site.warc.gz")
        with open(warc, "wb") as f:
            f.write(b"previous crawl")
        with self.assertRaises(SystemExit) as ctx:
            self._run_main(warc_path=warc)
        self.assertNotEqual(ctx.exception.code, 0)
        with open(warc, "rb") as f:
            self.assertEqual(f.read(), b"previous crawl")


if __name__ == "__main__":
    unittest.main()
