"""HTTPS origin for the browsertrix smoke test.

Acts like a bot-protected site: every request without the expected bypass
header gets a 403. Each request is logged as one JSON line so the checker can
verify header delivery and request spacing.
"""
import http.server
import json
import os
import ssl
import time

HEADER = "x-wdsoit-bot-bypass"
EXPECTED = os.environ["EXPECTED_BYPASS_VALUE"]

PAGES = {
    "/": ("text/html", b"<html><head><link rel='stylesheet' href='/style.css'></head><body>"
                       b"<h1>smoke home</h1><img src='/img.svg'><a href='/page2'>next</a></body></html>"),
    "/page2": ("text/html", b"<html><body><h1>smoke page two</h1></body></html>"),
    "/style.css": ("text/css", b"h1 { color: teal; }"),
    "/img.svg": ("image/svg+xml", b"<svg xmlns='http://www.w3.org/2000/svg' width='1' height='1'/>"),
}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        ok = self.headers.get(HEADER) == EXPECTED
        print(json.dumps({"t": time.time(), "path": self.path, "bypass": ok}), flush=True)
        if not ok:
            self._send(403, "text/plain", b"blocked: missing bot bypass header")
            return
        entry = PAGES.get(self.path.split("?")[0])
        if entry is None:
            self._send(404, "text/plain", b"not found")
            return
        self._send(200, *entry)

    def _send(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain("/certs/origin.pem", "/certs/origin.key")
server = http.server.ThreadingHTTPServer(("0.0.0.0", 8443), Handler)
server.socket = ctx.wrap_socket(server.socket, server_side=True)
server.serve_forever()
