"""Tests for the mitmproxy addon that sits in front of browsertrix-crawler.

browsertrix-crawler (v1.15.x) has no option for custom request headers, so the
browsertrix engine routes Chromium through this proxy, which adds the bypass
header to in-scope hosts and spaces out requests by the crawl delay.
The addon is plain Python and is tested here without mitmproxy installed.
"""
import asyncio
import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_DIR = os.path.join(HERE, "browsertrix", "proxy")
sys.path.insert(0, ADDON_DIR)
import bypass_proxy  # noqa: E402


class FakeRequest:
    def __init__(self, host):
        self.pretty_host = host
        self.headers = {}


class FakeFlow:
    def __init__(self, host):
        self.request = FakeRequest(host)


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.slept = []

    def monotonic(self):
        return self.now

    async def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def make_proxy(value="s3cret", hosts=("orfe.princeton.edu", "*.princeton.edu"), delay=1.0, clock=None):
    clock = clock or FakeClock()
    proxy = bypass_proxy.BypassProxy(
        header_name="x-wdsoit-bot-bypass",
        header_value=value,
        host_patterns=list(hosts),
        delay=delay,
        clock=clock.monotonic,
        sleep=clock.sleep,
    )
    return proxy, clock


def run(coro):
    return asyncio.run(coro)


class TestScope(unittest.TestCase):
    def test_exact_and_wildcard_hosts_are_in_scope(self):
        proxy, _ = make_proxy()
        self.assertTrue(proxy.in_scope("orfe.princeton.edu"))
        self.assertTrue(proxy.in_scope("www.princeton.edu"))
        self.assertTrue(proxy.in_scope("ORFE.Princeton.EDU"))

    def test_other_hosts_are_out_of_scope(self):
        proxy, _ = make_proxy()
        for host in ["cdn.jsdelivr.net", "princeton.edu.evil.com", "evilprinceton.edu", ""]:
            with self.subTest(host=host):
                self.assertFalse(proxy.in_scope(host))


class TestHeaderInjection(unittest.TestCase):
    def test_header_added_for_in_scope_hosts(self):
        proxy, _ = make_proxy()
        flow = FakeFlow("orfe.princeton.edu")
        run(proxy.request(flow))
        self.assertEqual(flow.request.headers["x-wdsoit-bot-bypass"], "s3cret")

    def test_header_never_sent_to_third_parties(self):
        proxy, _ = make_proxy()
        flow = FakeFlow("ajax.googleapis.com")
        run(proxy.request(flow))
        self.assertNotIn("x-wdsoit-bot-bypass", flow.request.headers)

    def test_no_header_when_no_value_configured(self):
        proxy, _ = make_proxy(value=None)
        flow = FakeFlow("orfe.princeton.edu")
        run(proxy.request(flow))
        self.assertEqual(flow.request.headers, {})


class TestThrottle(unittest.TestCase):
    def test_in_scope_requests_are_spaced_by_the_delay(self):
        proxy, clock = make_proxy(delay=1.0)
        run(proxy.request(FakeFlow("orfe.princeton.edu")))
        run(proxy.request(FakeFlow("www.princeton.edu")))
        self.assertEqual(clock.slept, [1.0])

    def test_only_remaining_delay_is_slept(self):
        proxy, clock = make_proxy(delay=1.0)
        run(proxy.request(FakeFlow("orfe.princeton.edu")))
        clock.now += 0.4
        run(proxy.request(FakeFlow("orfe.princeton.edu")))
        self.assertEqual(len(clock.slept), 1)
        self.assertAlmostEqual(clock.slept[0], 0.6)

    def test_third_party_requests_are_not_throttled(self):
        proxy, clock = make_proxy(delay=1.0)
        run(proxy.request(FakeFlow("orfe.princeton.edu")))
        run(proxy.request(FakeFlow("cdn.jsdelivr.net")))
        self.assertEqual(clock.slept, [])

    def test_zero_delay_never_sleeps(self):
        proxy, clock = make_proxy(delay=0)
        for _ in range(3):
            run(proxy.request(FakeFlow("orfe.princeton.edu")))
        self.assertEqual(clock.slept, [])

    def test_concurrent_browser_requests_are_serialized(self):
        # Chromium fires many subresource requests at once; each must still
        # wait its turn. Uses the real clock with a short delay.
        delay = 0.05
        proxy = bypass_proxy.BypassProxy("x-wdsoit-bot-bypass", "v", ["example.com"], delay)
        starts = []

        async def one():
            flow = FakeFlow("example.com")
            await proxy.request(flow)
            starts.append(time.monotonic())

        async def many():
            await asyncio.gather(*(one() for _ in range(4)))

        asyncio.run(many())
        starts.sort()
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        self.assertEqual(len(gaps), 3)
        for gap in gaps:
            self.assertGreaterEqual(gap, delay * 0.9)


class TestLoadConfig(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.secret_file = os.path.join(self.temp_dir, "bypass_header")

    def tearDown(self):
        for name in os.listdir(self.temp_dir):
            os.remove(os.path.join(self.temp_dir, name))
        os.rmdir(self.temp_dir)

    def env(self, **overrides):
        env = {
            "BYPASS_HOSTS": "orfe.princeton.edu,*.princeton.edu",
            "CRAWL_DELAY": "1",
            "BYPASS_HEADER_FILE": self.secret_file,
        }
        env.update(overrides)
        return env

    def test_valid_config(self):
        with open(self.secret_file, "w") as f:
            f.write("s3cret\n")
        cfg = bypass_proxy.load_config(self.env())
        self.assertEqual(cfg["header_name"], "x-wdsoit-bot-bypass")
        self.assertEqual(cfg["header_value"], "s3cret")
        self.assertEqual(cfg["host_patterns"], ["orfe.princeton.edu", "*.princeton.edu"])
        self.assertEqual(cfg["delay"], 1.0)

    def test_missing_or_empty_secret_means_no_header(self):
        self.assertIsNone(bypass_proxy.load_config(self.env())["header_value"])
        with open(self.secret_file, "w") as f:
            f.write("\n")
        self.assertIsNone(bypass_proxy.load_config(self.env())["header_value"])

    def test_delay_defaults_to_one_second(self):
        env = self.env()
        del env["CRAWL_DELAY"]
        self.assertEqual(bypass_proxy.load_config(env)["delay"], 1.0)

    def test_invalid_config_is_rejected(self):
        cases = {
            "no hosts": {"BYPASS_HOSTS": ""},
            "bad host": {"BYPASS_HOSTS": "orfe.princeton.edu,bad host!"},
            "bad delay": {"CRAWL_DELAY": "fast"},
            "negative delay": {"CRAWL_DELAY": "-1"},
            "huge delay": {"CRAWL_DELAY": "61"},
            "bad header name": {"BYPASS_HEADER_NAME": "x bad:header"},
        }
        for label, override in cases.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    bypass_proxy.load_config(self.env(**override))
        env = self.env()
        del env["BYPASS_HOSTS"]
        with self.assertRaises(ValueError):
            bypass_proxy.load_config(env)

    def test_check_cli_exit_codes(self):
        script = os.path.join(ADDON_DIR, "bypass_proxy.py")
        ok = subprocess.run([sys.executable, "-I", script, "--check"], env=self.env(),
                            capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        bad = subprocess.run([sys.executable, "-I", script, "--check"], env=self.env(CRAWL_DELAY="x"),
                             capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("CRAWL_DELAY", bad.stderr)

    def test_check_cli_never_prints_the_secret(self):
        with open(self.secret_file, "w") as f:
            f.write("s3cret-do-not-print")
        script = os.path.join(ADDON_DIR, "bypass_proxy.py")
        out = subprocess.run([sys.executable, "-I", script, "--check"], env=self.env(),
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("s3cret-do-not-print", out.stdout + out.stderr)
        self.assertIn("header: set", out.stdout)


if __name__ == "__main__":
    unittest.main()
