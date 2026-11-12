"""Verify a browsertrix smoke-test crawl.

Usage: check_wacz.py <wacz> <origin-log> <secret> <delay-seconds>

Fails (exit 1) unless:
  * the WACZ holds 200 responses for both origin pages and no 403s;
  * the bypass secret appears nowhere in the WACZ, compressed or not;
  * the origin saw the correct header on every request; and
  * consecutive origin requests were spaced by at least ~the delay.
"""
import gzip
import io
import json
import re
import sys
import zipfile

ORIGIN = "https://origin:8443"


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


def iter_warc_records(data):
    """Yield (lower-cased WARC headers, block bytes) for each WARC record."""
    pos = 0
    while pos < len(data):
        end = data.find(b"\r\n\r\n", pos)
        if end < 0:
            fail("truncated WARC record header")
        lines = data[pos:end].decode("utf-8", "replace").split("\r\n")
        if not lines[0].startswith("WARC/"):
            fail(f"expected a WARC version line, got {lines[0][:40]!r}")
        headers = {}
        for line in lines[1:]:
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
        start = end + 4
        length = int(headers["content-length"])
        yield headers, data[start:start + length]
        pos = start + length
        while data[pos:pos + 2] == b"\r\n":
            pos += 2


def main(wacz_path, log_path, secret, delay):
    secret_b = secret.encode()
    statuses = {}
    with zipfile.ZipFile(wacz_path) as z:
        names = z.namelist()
        if not any(n.startswith("archive/") and ".warc" in n for n in names):
            fail(f"no WARC files inside {wacz_path}: {names}")
        for name in names:
            raw = z.read(name)
            data = raw
            if name.endswith(".gz"):
                data = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            if secret_b in raw or secret_b in data:
                fail(f"bypass secret found in {name}")
            if name.startswith("archive/"):
                for headers, block in iter_warc_records(data):
                    if headers.get("warc-type") != "response":
                        continue
                    match = re.match(rb"HTTP/\d(?:\.\d)? (\d{3})", block)
                    if not match:
                        fail(f"response record without an HTTP status line in {name}")
                    statuses.setdefault(headers["warc-target-uri"], set()).add(int(match.group(1)))

    for page in ("/", "/page2"):
        got = statuses.get(ORIGIN + page)
        if got != {200}:
            fail(f"expected a 200 response for {page} in the WACZ, got {got}; all: {statuses}")
    blocked = [u for u, s in statuses.items() if 403 in s]
    if blocked:
        fail(f"403 responses archived for {blocked}")

    requests = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            start = line.find("{")
            if start >= 0:
                try:
                    requests.append(json.loads(line[start:]))
                except json.JSONDecodeError:
                    pass
    if len(requests) < 3:
        fail(f"origin logged only {len(requests)} requests")
    missing = [r["path"] for r in requests if not r["bypass"]]
    if missing:
        fail(f"requests reached the origin without the bypass header: {missing}")

    times = sorted(r["t"] for r in requests)
    gaps = [b - a for a, b in zip(times, times[1:])]
    if min(gaps) < delay * 0.9:
        fail(f"requests not throttled to {delay}s: smallest gap {min(gaps):.3f}s")

    print(f"OK: {len(requests)} origin requests, all with the header, min gap {min(gaps):.2f}s; "
          f"pages archived: {sorted(statuses)}; secret absent from WACZ")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]))
