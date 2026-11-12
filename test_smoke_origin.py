"""The smoke-test HTTPS origin must not accept obsolete TLS versions."""
import importlib.util
import os
import shutil
import ssl
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "tests", "browsertrix_smoke", "origin", "server.py")


def load_server():
    spec = importlib.util.spec_from_file_location("smoke_origin_server", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestSmokeOriginTls(unittest.TestCase):
    def setUp(self):
        if not shutil.which("openssl"):
            self.fail("openssl is required to generate a test certificate")
        self.temp_dir = tempfile.mkdtemp()
        self.cert = os.path.join(self.temp_dir, "cert.pem")
        self.key = os.path.join(self.temp_dir, "key.pem")
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
             "-subj", "/CN=origin", "-keyout", self.key, "-out", self.cert],
            check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_minimum_tls_version_is_1_2(self):
        ctx = load_server().make_tls_context(self.cert, self.key)
        self.assertGreaterEqual(ctx.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertNotEqual(ctx.minimum_version, ssl.TLSVersion.MINIMUM_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
