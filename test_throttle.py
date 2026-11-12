"""Tests for crawl throttling: every request to the crawled site is spaced out
by a configurable delay so the archiver stays polite to the origin server."""
import inspect
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import scraper


class TestPoliteGet(unittest.TestCase):
    def setUp(self):
        scraper.crawl_delay = 1.0
        scraper._last_request_at = None
        scraper.headers = {}

    def tearDown(self):
        scraper.crawl_delay = 0.0
        scraper._last_request_at = None

    @patch('scraper.time.sleep')
    @patch('scraper.time.monotonic')
    @patch('scraper.session.get')
    def test_first_request_is_not_delayed(self, mock_get, mock_clock, mock_sleep):
        mock_clock.return_value = 100.0
        scraper.polite_get("https://example.com/")
        mock_sleep.assert_not_called()
        mock_get.assert_called_once()

    @patch('scraper.time.sleep')
    @patch('scraper.time.monotonic')
    @patch('scraper.session.get')
    def test_back_to_back_requests_wait_for_the_full_delay(self, mock_get, mock_clock, mock_sleep):
        mock_clock.return_value = 100.0
        scraper.polite_get("https://example.com/a")
        scraper.polite_get("https://example.com/b")
        mock_sleep.assert_called_once()
        self.assertAlmostEqual(mock_sleep.call_args[0][0], 1.0)
        self.assertEqual(mock_get.call_count, 2)

    @patch('scraper.time.sleep')
    @patch('scraper.time.monotonic')
    @patch('scraper.session.get')
    def test_only_the_remaining_delay_is_slept(self, mock_get, mock_clock, mock_sleep):
        # First request finishes at t=100.0; the next starts at t=100.25.
        mock_clock.side_effect = [100.0, 100.25, 100.25]
        scraper.polite_get("https://example.com/a")
        scraper.polite_get("https://example.com/b")
        mock_sleep.assert_called_once()
        self.assertAlmostEqual(mock_sleep.call_args[0][0], 0.75)

    @patch('scraper.time.sleep')
    @patch('scraper.time.monotonic')
    @patch('scraper.session.get')
    def test_no_wait_once_the_delay_has_elapsed(self, mock_get, mock_clock, mock_sleep):
        mock_clock.side_effect = [100.0, 102.0, 102.0]
        scraper.polite_get("https://example.com/a")
        scraper.polite_get("https://example.com/b")
        mock_sleep.assert_not_called()

    @patch('scraper.time.sleep')
    @patch('scraper.session.get')
    def test_zero_delay_never_sleeps(self, mock_get, mock_sleep):
        scraper.crawl_delay = 0.0
        for _ in range(3):
            scraper.polite_get("https://example.com/")
        mock_sleep.assert_not_called()
        self.assertEqual(mock_get.call_count, 3)

    @patch('scraper.time.sleep')
    @patch('scraper.time.monotonic')
    @patch('scraper.session.get')
    def test_failed_request_still_counts_toward_the_delay(self, mock_get, mock_clock, mock_sleep):
        mock_clock.return_value = 100.0
        mock_get.side_effect = [ConnectionError("boom"), MagicMock()]
        with self.assertRaises(ConnectionError):
            scraper.polite_get("https://example.com/a")
        scraper.polite_get("https://example.com/b")
        mock_sleep.assert_called_once()

    @patch('scraper.session.get')
    def test_arguments_are_passed_through(self, mock_get):
        scraper.crawl_delay = 0.0
        scraper.polite_get("https://example.com/x", headers={"A": "b"}, stream=True, timeout=20)
        mock_get.assert_called_once_with("https://example.com/x", headers={"A": "b"}, stream=True, timeout=20)


class TestEveryFetchIsThrottled(unittest.TestCase):
    """Guards against a new call site quietly bypassing the throttle."""

    def test_session_get_is_only_called_from_polite_get(self):
        source = inspect.getsource(scraper)
        self.assertEqual(
            source.count("session.get("), 1,
            "Fetch the crawled site through polite_get() so the crawl delay applies.",
        )
        self.assertIn("session.get(", inspect.getsource(scraper.polite_get))

    @patch('scraper.polite_get')
    def test_download_asset_uses_polite_get(self, mock_polite):
        temp_dir = tempfile.mkdtemp()
        scraper.output_dir = temp_dir
        scraper.downloaded_assets = {}
        scraper.allowed_asset_domains = ["example.com"]
        try:
            resp = MagicMock(status_code=200)
            resp.iter_content.return_value = [b"x"]
            mock_polite.return_value = resp
            scraper.download_asset("https://example.com/logo.png")
            mock_polite.assert_called_once()
            self.assertEqual(mock_polite.call_args[0][0], "https://example.com/logo.png")
        finally:
            scraper.output_dir = "/output"
            shutil.rmtree(temp_dir)

    @patch('scraper.polite_get')
    def test_crawl_page_uses_polite_get(self, mock_polite):
        scraper.crawled_pages = set()
        mock_polite.return_value = MagicMock(status_code=404)
        scraper.crawl_page("https://example.com/")
        mock_polite.assert_called_once()
        self.assertEqual(mock_polite.call_args[0][0], "https://example.com/")


class TestParseCrawlDelay(unittest.TestCase):
    def test_missing_value_uses_the_polite_default(self):
        self.assertEqual(scraper.parse_crawl_delay(None), scraper.DEFAULT_CRAWL_DELAY)
        self.assertEqual(scraper.DEFAULT_CRAWL_DELAY, 1.0)

    def test_accepts_numbers_and_numeric_strings(self):
        self.assertEqual(scraper.parse_crawl_delay(2), 2.0)
        self.assertEqual(scraper.parse_crawl_delay("0.5"), 0.5)
        self.assertEqual(scraper.parse_crawl_delay(0), 0.0)

    def test_rejects_invalid_values(self):
        for bad in ["abc", "", -1, "-0.1", float("nan"), float("inf"), True, [], 61]:
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    scraper.parse_crawl_delay(bad)


class TestMainDelayConfig(unittest.TestCase):
    def _write_config(self, temp_dir, **extra):
        config = {"url": "https://example.com/", "output_dir": temp_dir}
        config.update(extra)
        path = os.path.join(temp_dir, "config.json")
        with open(path, "w") as f:
            json.dump(config, f)
        return path

    def tearDown(self):
        scraper.crawl_delay = 0.0

    @patch('scraper.crawl_page')
    def test_main_applies_configured_delay(self, mock_crawl):
        temp_dir = tempfile.mkdtemp()
        try:
            path = self._write_config(temp_dir, delay=0.5)
            with patch('sys.argv', ['scraper.py', path]):
                scraper.main()
            self.assertEqual(scraper.crawl_delay, 0.5)
            mock_crawl.assert_called_once()
        finally:
            shutil.rmtree(temp_dir)

    @patch('scraper.crawl_page')
    def test_main_defaults_to_polite_delay(self, mock_crawl):
        temp_dir = tempfile.mkdtemp()
        try:
            path = self._write_config(temp_dir)
            with patch('sys.argv', ['scraper.py', path]):
                scraper.main()
            self.assertEqual(scraper.crawl_delay, 1.0)
        finally:
            shutil.rmtree(temp_dir)

    @patch('scraper.crawl_page')
    def test_main_fails_fast_on_invalid_delay(self, mock_crawl):
        temp_dir = tempfile.mkdtemp()
        try:
            path = self._write_config(temp_dir, delay="fast")
            with patch('sys.argv', ['scraper.py', path]):
                with self.assertRaises(SystemExit) as ctx:
                    scraper.main()
            self.assertNotEqual(ctx.exception.code, 0)
            mock_crawl.assert_not_called()
        finally:
            shutil.rmtree(temp_dir)


if __name__ == '__main__':
    unittest.main()
