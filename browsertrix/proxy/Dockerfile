# Header-injecting, throttling proxy that sits in front of browsertrix-crawler.
# Upstream TLS certificates are verified (mitmproxy's default). Extra mitmdump
# options can be appended via MITMDUMP_EXTRA_ARGS, e.g. to trust a test CA.
FROM mitmproxy/mitmproxy:12.2.3
COPY bypass_proxy.py /addon/bypass_proxy.py
# Validate configuration first so a bad setting stops the crawl instead of
# letting it run without the header or the throttle.
CMD ["sh", "-c", "python3 -I /addon/bypass_proxy.py --check && exec mitmdump --quiet --listen-port 8080 -s /addon/bypass_proxy.py ${MITMDUMP_EXTRA_ARGS:-}"]
HEALTHCHECK --interval=2s --timeout=2s --retries=15 \
  CMD python3 -I -c "import socket; socket.create_connection(('127.0.0.1', 8080), 1).close()"
