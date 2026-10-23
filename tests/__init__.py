# keep tests out of the real radio log, clips, archive, driver, settings and prompt files
import json
import tempfile
from pathlib import Path
from unittest import mock

from engineer import archive, driver, pitstops, prompts, radio, radiolog, settings

radiolog.CLIPS = radio.CLIPS = Path(tempfile.mkdtemp(prefix="re-radio-"))
radiolog.LOG = radiolog.CLIPS / "messages.jsonl"
archive.DB = Path(tempfile.mkdtemp(prefix="re-archive-")) / "archive.db"
archive.SESSIONS = archive.DB.parent / "sessions"  # the catalogue finds recordings here when it heals paths
driver.FILE = Path(tempfile.mkdtemp(prefix="re-driver-")) / "driver.json"
settings.FILE = driver.FILE.parent / "settings.json"
prompts.CUSTOM = driver.FILE.parent / "prompts"
pitstops._table.append({"tracks": {}, "usual": None})  # the shipped figures change every release


def radio_rows(test):
    """Gives `test` a radio log of its own; returns a reader for its rows of one kind."""
    log = Path(tempfile.mkdtemp(prefix="re-radiolog-")) / "messages.jsonl"
    patcher = mock.patch.object(radiolog, "LOG", log)
    patcher.start()
    test.addCleanup(patcher.stop)
    return lambda kind: [r for r in map(json.loads, log.read_text().splitlines()) if r["kind"] == kind] if log.exists() else []
