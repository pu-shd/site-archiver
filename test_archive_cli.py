"""archive.sh must reject invalid politeness and archive options before it
checks dependencies, touches GitHub, or starts any crawl."""
import os
import subprocess
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "archive.sh")


def run(*args):
    return subprocess.run(["bash", SCRIPT, *args], capture_output=True, text=True, timeout=30,
                          env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "/tmp")})


class TestArchiveCliValidation(unittest.TestCase):
    def test_invalid_delay_is_rejected(self):
        for bad in ["abc", "-1", "61", "1e3", ""]:
            with self.subTest(delay=bad):
                result = run("--delay", bad)
                self.assertEqual(result.returncode, 1)
                self.assertIn("--delay must be a number of seconds", result.stdout)

    def test_invalid_page_limit_is_rejected(self):
        for bad in ["x", "-2", "1.5"]:
            with self.subTest(limit=bad):
                result = run("--page-limit", bad)
                self.assertEqual(result.returncode, 1)
                self.assertIn("--page-limit must be a non-negative integer", result.stdout)

    def test_help_documents_new_options(self):
        result = run("--help")
        self.assertEqual(result.returncode, 0)
        for flag in ["--delay", "--warc", "--browsertrix", "--page-limit", "--archive-dir"]:
            self.assertIn(flag, result.stdout)


if __name__ == "__main__":
    unittest.main()
