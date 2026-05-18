"""SQLite database access: schema, settings cache, event log, async helpers."""
import asyncio
import sqlite3
import time
from contextlib import contextmanager
from typing import Optional

from .config import DB_PATH, EVENT_RING_LIMIT, METRICS_RETENTION_DAYS, log


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_type TEXT NOT NULL DEFAULT 'docker',
                name TEXT NOT NULL DEFAULT '',
                container TEXT NOT NULL DEFAULT '',
                trigger TEXT NOT NULL,
                action TEXT NOT NULL DEFAULT '',
                command TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS wan_metrics (
                ts INTEGER PRIMARY KEY,
                rx_mbps REAL,
                tx_mbps REAL,
                latency_ms REAL,
                active_wan TEXT
            );
            """
        )
        cols = {r[1] for r in conn.execute("PRAGMA table_info(rules)").fetchall()}
        for col, ddl in (
            ("rule_type",      "TEXT NOT NULL DEFAULT 'docker'"),
            ("name",           "TEXT NOT NULL DEFAULT ''"),
            ("command",        "TEXT NOT NULL DEFAULT ''"),
            ("delay_seconds",  "INTEGER NOT NULL DEFAULT 0"),
            ("sort_order",     "INTEGER NOT NULL DEFAULT 0"),
        ):
            if col not in cols:
                conn.execute(f"ALTER TABLE rules ADD COLUMN {col} {ddl}")
                if col == "sort_order":
                    # seed existing rows so they keep their current order
                    conn.execute("UPDATE rules SET sort_order = id")

        evcols = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
        if evcols.get("ts", "").upper() == "TEXT":
            log.info("Migrating events.ts TEXT -> INTEGER")
            conn.executescript(
                """
                CREATE TABLE events_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL
                );
                INSERT INTO events_new(id, ts, level, message)
                SELECT id, CAST(strftime('%s', ts) AS INTEGER), level, message
                  FROM events
                 WHERE ts IS NOT NULL;
                DROP TABLE events;
                ALTER TABLE events_new RENAME TO events;
                CREATE INDEX idx_events_ts ON events(ts);
                """
            )


# ---------------------------------------------------------------------------
# Settings cache
# ---------------------------------------------------------------------------
_settings_cache: dict[str, Optional[str]] = {}
_cache_loaded = False


def _load_cache():
    global _cache_loaded
    with db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    _settings_cache.clear()
    for r in rows:
        _settings_cache[r["key"]] = r["value"]
    _cache_loaded = True


def invalidate_cache():
    global _cache_loaded
    _cache_loaded = False


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    if not _cache_loaded:
        _load_cache()
    val = _settings_cache.get(key)
    return val if val is not None else default


def set_setting(key: str, value: str):
    if not _cache_loaded:
        _load_cache()
    with db() as conn:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
    _settings_cache[key] = value


def delete_setting(key: str):
    with db() as conn:
        conn.execute("DELETE FROM settings WHERE key=?", (key,))
    _settings_cache.pop(key, None)


def get_state(key: str) -> Optional[str]:
    with db() as conn:
        row = conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None


def set_state(key: str, value: str):
    with db() as conn:
        conn.execute(
            "INSERT INTO state(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
def log_event(level: str, message: str):
    ts = int(time.time())
    with db() as conn:
        conn.execute(
            "INSERT INTO events(ts, level, message) VALUES(?,?,?)",
            (ts, level, message),
        )
        conn.execute(
            "DELETE FROM events WHERE id NOT IN "
            "(SELECT id FROM events ORDER BY id DESC LIMIT ?)",
            (EVENT_RING_LIMIT,),
        )
    log.info("[%s] %s", level, message)


def purge_old_events(retention_days: int) -> int:
    cutoff = int(time.time()) - retention_days * 86400
    with db() as conn:
        n = conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,)).rowcount
    if n:
        log.info("Purged %d events older than %d days", n, retention_days)
    return n


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def write_metric(info: dict):
    ts = int(time.time())
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO wan_metrics(ts, rx_mbps, tx_mbps, latency_ms, active_wan) "
            "VALUES(?,?,?,?,?)",
            (
                ts,
                info.get("active_wan_rx_mbps"),
                info.get("active_wan_tx_mbps"),
                info.get("active_wan_latency"),
                info.get("active_wan"),
            ),
        )
        conn.execute(
            "DELETE FROM wan_metrics WHERE ts < ?",
            (ts - METRICS_RETENTION_DAYS * 86400,),
        )


# ---------------------------------------------------------------------------
# Async wrappers (sqlite3 is blocking)
# ---------------------------------------------------------------------------
async def a_log_event(level: str, message: str):
    await asyncio.to_thread(log_event, level, message)


async def a_write_metric(info: dict):
    await asyncio.to_thread(write_metric, info)


async def a_set_state(key: str, value: str):
    await asyncio.to_thread(set_state, key, value)
