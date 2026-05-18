"""Full backup / restore: settings, rules, events."""
import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..auth import require_auth
from ..db import db, invalidate_cache, log_event
from .settings import EXPORT_KEYS   # single source of truth for all setting keys

router = APIRouter(prefix="/api/backup")

BACKUP_VERSION = 3


@router.get("/export")
async def export_backup(_: bool = Depends(require_auth)):
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

    payload = {
        "wanifi_backup_version": BACKUP_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "settings": settings,
        "rules": rules,
        "events": events,
    }
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

    version = payload.get("wanifi_backup_version") or payload.get("wanifi_export_version")
    if not version:
        raise HTTPException(400, "Not a valid WaniFi backup file")
    if version > BACKUP_VERSION:
        raise HTTPException(400, f"Backup version {version} is newer than supported ({BACKUP_VERSION})")

    counts = {"settings": 0, "rules": 0, "events": 0}

    # v1 was a flat settings-only payload; v2+ use a nested "settings" key
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

    log_event(
        "info",
        f"Backup restored: {counts['settings']} settings, "
        f"{counts['rules']} rules, {counts['events']} events",
    )
    return {"ok": True, "imported": counts}
