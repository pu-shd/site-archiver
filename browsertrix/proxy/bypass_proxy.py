"""mitmproxy addon used by the browsertrix engine.

browsertrix-crawler has no option for custom request headers (it only sends
Authorization for user:pass@ seed URLs), but it can route Chromium and its own
direct fetches through --proxyServer, and it ignores TLS errors when it does.
This addon runs in that proxy and:

  * adds the bot bypass header to requests for in-scope hosts only, so the
    secret never reaches third-party CDNs; and
  * spaces requests to in-scope hosts by CRAWL_DELAY seconds, so the browser
    engine is as polite as the requests engine.

The header is added after Chromium has recorded the request, so it never
appears in the WARC/WACZ that browsertrix writes.

Configuration (environment):
  BYPASS_HOSTS        comma-separated host patterns, e.g. "site.edu,*.site.edu"
  CRAWL_DELAY         seconds between in-scope requests, 0-60 (default 1)
  BYPASS_HEADER_NAME  header to add (default x-wdsoit-bot-bypass)
  BYPASS_HEADER_FILE  file holding the header value (default
                      /run/secrets/bypass_header); missing or empty = no header

Run `python bypass_proxy.py --check` to validate the configuration and exit.
"""
import asyncio
import fnmatch
import math
import os
import re
import sys
import time

DEFAULT_HEADER_NAME = "x-wdsoit-bot-bypass"
DEFAULT_HEADER_FILE = "/run/secrets/bypass_header"
DEFAULT_DELAY = 1.0
MAX_DELAY = 60.0

_HOST_PATTERN = re.compile(r"^(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$")
_HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$")


def _parse_delay(raw):
    if raw is None:
        return DEFAULT_DELAY
    try:
        delay = float(raw)
    except ValueError:
        raise ValueError(f"CRAWL_DELAY must be a number of seconds, got {raw!r}") from None
    if not math.isfinite(delay) or delay < 0 or delay > MAX_DELAY:
        raise ValueError(f"CRAWL_DELAY must be between 0 and {MAX_DELAY:g}, got {raw!r}")
    return delay


def load_config(env):
    """Read and validate configuration; raises ValueError on bad input."""
    hosts = [h.strip().lower() for h in env.get("BYPASS_HOSTS", "").split(",") if h.strip()]
    if not hosts:
        raise ValueError("BYPASS_HOSTS must list at least one host")
    for host in hosts:
        if not _HOST_PATTERN.match(host):
            raise ValueError(f"BYPASS_HOSTS has an invalid host pattern: {host!r}")

    header_name = env.get("BYPASS_HEADER_NAME", DEFAULT_HEADER_NAME)
    if not _HEADER_NAME.match(header_name):
        raise ValueError(f"BYPASS_HEADER_NAME is not a valid header name: {header_name!r}")

    header_value = None
    header_file = env.get("BYPASS_HEADER_FILE", DEFAULT_HEADER_FILE)
    if os.path.isfile(header_file):
        with open(header_file, "r", encoding="utf-8") as f:
            header_value = f.read().strip() or None
    if header_value is not None and ("\r" in header_value or "\n" in header_value):
        raise ValueError("bypass header value must be a single line")

    return {
        "header_name": header_name,
        "header_value": header_value,
        "host_patterns": hosts,
        "delay": _parse_delay(env.get("CRAWL_DELAY")),
    }


class BypassProxy:
    def __init__(self, header_name, header_value, host_patterns, delay,
                 clock=time.monotonic, sleep=asyncio.sleep):
        self.header_name = header_name
        self.header_value = header_value
        self.host_patterns = [p.lower() for p in host_patterns]
        self.delay = delay
        self._clock = clock
        self._sleep = sleep
        self._lock = None
        self._last_start = None

    def in_scope(self, host):
        host = (host or "").lower()
        return bool(host) and any(fnmatch.fnmatchcase(host, p) for p in self.host_patterns)

    async def _throttle(self):
        if self.delay <= 0:
            return
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._last_start is not None:
                remaining = self.delay - (self._clock() - self._last_start)
                if remaining > 0:
                    await self._sleep(remaining)
            self._last_start = self._clock()

    async def request(self, flow):
        """mitmproxy hook: called for each (decrypted) client request."""
        if not self.in_scope(flow.request.pretty_host):
            return
        await self._throttle()
        if self.header_value:
            flow.request.headers[self.header_name] = self.header_value


def _describe(cfg):
    return (f"bypass proxy: hosts={','.join(cfg['host_patterns'])} delay={cfg['delay']:g}s "
            f"header: {'set' if cfg['header_value'] else 'not set'}")


# mitmproxy loads this file as a script and reads `addons`. Configuration was
# validated by `--check` before mitmdump started; outside mitmproxy (tests)
# BYPASS_HOSTS is unset and no addon is built.
addons = []
if os.environ.get("BYPASS_HOSTS") and __name__ != "__main__":
    _cfg = load_config(os.environ)
    addons = [BypassProxy(_cfg["header_name"], _cfg["header_value"], _cfg["host_patterns"], _cfg["delay"])]


if __name__ == "__main__":
    if sys.argv[1:] != ["--check"]:
        print("usage: bypass_proxy.py --check", file=sys.stderr)
        sys.exit(2)
    try:
        print(_describe(load_config(os.environ)))
    except ValueError as e:
        print(f"bypass proxy configuration error: {e}", file=sys.stderr)
        sys.exit(1)
