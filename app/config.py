"""Application-wide constants, paths, and logging configuration."""
import logging
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "wanifi.db"

POLL_INTERVAL_DEFAULT = 60
LIVE_INTERVAL = 2
METRICS_WRITE_INTERVAL = 30
METRICS_RETENTION_DAYS = 30
EVENT_RING_LIMIT = 5000
SESSION_MAX_AGE = 60 * 60 * 24 * 30
SESSION_IDLE_TIMEOUT = 60 * 60 * 24 * 30

UNIFI_HTTP_TIMEOUT = 10.0
NTFY_HTTP_TIMEOUT = 10.0

APP_VERSION = "0.6.0"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("wanifi")
