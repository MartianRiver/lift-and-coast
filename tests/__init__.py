# keep tests out of the real radio log, clips, archive and driver settings
import tempfile
from pathlib import Path

from engineer import archive, driver, radio, radiolog

radiolog.CLIPS = radio.CLIPS = Path(tempfile.mkdtemp(prefix="re-radio-"))
radiolog.LOG = radiolog.CLIPS / "messages.jsonl"
archive.DB = Path(tempfile.mkdtemp(prefix="re-archive-")) / "archive.db"
driver.FILE = Path(tempfile.mkdtemp(prefix="re-driver-")) / "driver.json"
