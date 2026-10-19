"""This copy's version: pyproject's, plus `git describe` when the clone isn't exactly on that release,
so a log or a bug report says which commit it came from."""
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def version():
    base = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    try:
        out = subprocess.run(["git", "describe", "--tags", "--dirty"], cwd=ROOT, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):  # no git, or not a clone
        return base
    where = out.stdout.strip()
    return base if not where or where == f"v{base}" else f"{base} ({where})"  # a failed describe prints nothing


VERSION = version()
