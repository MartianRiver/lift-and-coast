"""The version a log or bug report shows: the release, or the release plus which commit."""
import subprocess
import tomllib
import unittest
from unittest import mock

from engineer import version

RELEASE = tomllib.loads((version.ROOT / "pyproject.toml").read_text())["project"]["version"]


def describing(stdout, code=0):
    return mock.patch.object(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, code, stdout, ""))


class Version(unittest.TestCase):
    def test_on_the_release_itself_just_the_number(self):
        with describing(f"v{RELEASE}\n"):
            self.assertEqual(version.version(), RELEASE)

    def test_past_the_release_says_which_commit(self):
        with describing(f"v{RELEASE}-8-g67efc3a-dirty\n"):
            self.assertEqual(version.version(), f"{RELEASE} (v{RELEASE}-8-g67efc3a-dirty)")

    def test_without_git_or_tags_the_release_number(self):
        with describing("", code=128):
            self.assertEqual(version.version(), RELEASE)

        def missing(*a, **kw):
            raise FileNotFoundError("git")
        with mock.patch.object(subprocess, "run", missing):
            self.assertEqual(version.version(), RELEASE)


if __name__ == "__main__":
    unittest.main()
