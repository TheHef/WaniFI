"""Full backup / restore: settings, rules, events."""
import json
import re
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..auth import require_auth
from ..config import BACKUP_DIR
from ..db import db, get_setting, invalidate_cache, log_event, set_setting
from .settings import EXPORT_KEYS   # single source of truth for all setting keys

router = APIRouter(prefix="/api/backup")

BACKUP_VERSION = 3

_SAFE_NAME_RE = re.compile(r'^wanifi_[a-zA-Z0-9_-]+\.json$')


def _safe_name(name: str) -> bool:
    return bool(_SAFE_NAME_RE.match(name))


# ── Shared helpers ────────────────────────────────────────────────────────────

def _build_payload() -> dict:
    """Build the full backup payload (shared by export, save, and scheduled backup)."""
    with db() as conn:
        rows = conn.execute(
            "SELECT key, value FROM settings WHERE key IN ({})".format(
                ",".join("?" * len(EXPORT_KEYS))
            ),
            EXPORT_KEYS,
        ).fetchall()
        settings = {r["key"]: r["value"] for r in rows}

        rules = [dict(r) for r in conn.execute(
            "SELECT rule_type, name, container, trigger, action, command, "
            "enabled, delay_seconds, sort_order "
            "FROM rules ORDER BY sort_order, id"
        ).fetchall()]

        events = [dict(r) for r in conn.execute(
            "SELECT ts, level, message FROM events ORDER BY id"
        ).fetchall()]

    return {
        "wanifi_backup_version": BACKUP_VERSION,
        "exported_at":           datetime.now(timezone.utc).isoformat(),
        "settings":              settings,
        "rules":                 rules,
        "events":                events,
    }


def _apply_payload(payload: dict) -> dict:
    """Write a backup payload into the DB. Returns counts dict."""
    version = payload.get("wanifi_backup_version") or payload.get("wanifi_export_version")
    if not version:
        raise ValueError("Not a valid WaniFi backup file")
    if version > BACKUP_VERSION:
        raise ValueError(f"Backup version {version} is newer than supported ({BACKUP_VERSION})")

    counts = {"settings": 0, "rules": 0, "events": 0}
    settings = payload.get("settings")
    if settings is None and version == 1:
        settings = {k: payload[k] for k in EXPORT_KEYS if k in payload}

    with db() as conn:
        if isinstance(settings, dict):
            for k, v in settings.items():
                if k not in EXPORT_KEYS or v in (None, ""):
                    continue
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (k, str(v)),
                )
                counts["settings"] += 1

        rules = payload.get("rules")
        if isinstance(rules, list):
            conn.execute("DELETE FROM rules")
            for idx, r in enumerate(rules):
                conn.execute(
                    "INSERT INTO rules"
                    "(rule_type, name, container, trigger, action, command, "
                    " enabled, delay_seconds, sort_order) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        r.get("rule_type", "docker"),
                        r.get("name", ""),
                        r.get("container", ""),
                        r.get("trigger", "failover"),
                        r.get("action", ""),
                        r.get("command", ""),
                        1 if r.get("enabled", 1) else 0,
                        int(r.get("delay_seconds", 0)),
                        int(r.get("sort_order", idx)),
                    ),
                )
                counts["rules"] += 1

        events = payload.get("events")
        if isinstance(events, list):
            conn.execute("DELETE FROM events")
            for e in events:
                ts = e.get("ts")
                if isinstance(ts, str):
                    try:
                        ts = int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
                    except Exception:
                        continue
                if not isinstance(ts, int):
                    continue
                conn.execute(
                    "INSERT INTO events(ts, level, message) VALUES(?, ?, ?)",
                    (ts, e.get("level", "info"), e.get("message", "")),
                )
                counts["events"] += 1

    invalidate_cache()
    return counts


def _enforce_retention(prefix: str, retention: int):
    """Delete oldest auto backups beyond the retention count."""
    files = sorted(
        BACKUP_DIR.glob(f"wanifi_{prefix}_*.json"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    for old in files[retention:]:
        try:
            old.unlink()
        except Exception:
            pass


# ── Existing endpoints ────────────────────────────────────────────────────────

@router.get("/export")
async def export_backup(_: bool = Depends(require_auth)):
    payload  = _build_payload()
    filename = f"wanifi-backup-{time.strftime('%Y%m%d-%H%M%S')}.json"
    return Response(
        content=json.dumps(payload, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import")
async def import_backup(request: Request, _: bool = Depends(require_auth)):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    try:
        counts = _apply_payload(payload)
    except ValueError as e:
        raise HTTPException(400, str(e))
    log_event(
        "info",
        f"Backup restored: {counts['settings']} settings, "
        f"{counts['rules']} rules, {counts['events']} events",
    )
    return {"ok": True, "imported": counts}


# ── Saved-backup endpoints ────────────────────────────────────────────────────

@router.post("/save")
async def save_backup(_: bool = Depends(require_auth)):
    """Save a manual backup to the on-disk backup store."""
    payload  = _build_payload()
    filename = f"wanifi_manual_{time.strftime('%Y%m%d-%H%M%S')}.json"
    path     = BACKUP_DIR / filename
    path.write_text(json.dumps(payload, indent=2))
    return {"ok": True, "name": filename, "size": path.stat().st_size}


@router.get("/list")
async def list_backups(_: bool = Depends(require_auth)):
    """Return metadata for all saved backups, newest first."""
    files = sorted(
        BACKUP_DIR.glob("wanifi_*.json"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    result = []
    for f in files:
        stat = f.stat()
        result.append({
            "name":       f.name,
            "size":       stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "type":       "auto" if "_auto_" in f.name else "manual",
        })
    return result


@router.get("/download/{name}")
async def download_saved_backup(name: str, _: bool = Depends(require_auth)):
    if not _safe_name(name):
        raise HTTPException(400, "Invalid filename")
    path = BACKUP_DIR / name
    if not path.exists():
        raise HTTPException(404, "Backup not found")
    return Response(
        content=path.read_bytes(),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/restore-saved/{name}")
async def restore_saved_backup(name: str, _: bool = Depends(require_auth)):
    if not _safe_name(name):
        raise HTTPException(400, "Invalid filename")
    path = BACKUP_DIR / name
    if not path.exists():
        raise HTTPException(404, "Backup not found")
    try:
        payload = json.loads(path.read_text())
        counts  = _apply_payload(payload)
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(400, str(e))
    log_event(
        "info",
        f"Backup restored from {name}: {counts['settings']} settings, "
        f"{counts['rules']} rules, {counts['events']} events",
    )
    return {"ok": True, "imported": counts}


@router.delete("/{name}")
async def delete_backup(name: str, _: bool = Depends(require_auth)):
    if not _safe_name(name):
        raise HTTPException(400, "Invalid filename")
    path = BACKUP_DIR / name
    if path.exists():
        path.unlink()
    return {"ok": True}


# ── Schedule settings ─────────────────────────────────────────────────────────

@router.get("/schedule")
async def get_backup_schedule(_: bool = Depends(require_auth)):
    return {
        "enabled":   get_setting("backup_schedule_enabled",  "0") == "1",
        "interval":  get_setting("backup_schedule_interval", "daily"),
        "time":      get_setting("backup_schedule_time",     "02:00"),
        "retention": int(get_setting("backup_retention_count", "10")),
    }


@router.post("/schedule")
async def save_backup_schedule(request: Request, _: bool = Depends(require_auth)):
    body = await request.json()
    set_setting("backup_schedule_enabled",  "1" if body.get("enabled") else "0")
    set_setting("backup_schedule_interval", body.get("interval", "daily"))
    # Validate time format HH:MM
    raw_time = body.get("time", "02:00")
    try:
        h, m = map(int, raw_time.split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
        set_setting("backup_schedule_time", f"{h:02d}:{m:02d}")
    except Exception:
        set_setting("backup_schedule_time", "02:00")
    try:
        retention = max(1, int(body.get("retention", 10)))
    except (TypeError, ValueError):
        retention = 10
    set_setting("backup_retention_count", str(retention))
    return {"ok": True}
