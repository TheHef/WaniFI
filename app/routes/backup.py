"""Full backup / restore: settings, rules, events."""
import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..auth import require_auth
from ..db import db, log_event

router = APIRouter(prefix="/api/backup")

BACKUP_VERSION = 2

SETTINGS_KEYS = (
    "unifi_host", "unifi_api_key", "unifi_site",
    "primary_wan", "failover_wan",
    "primary_wan_name", "failover_wan_name",
    "poll_interval", "event_retention_days",
    "latency_threshold_ms", "latency_cooldown_min",
    "ntfy_url", "ntfy_topic", "ntfy_token",
    "ntfy_on_failover", "ntfy_on_restored",
    "ntfy_on_error", "ntfy_on_high_latency",
    "qb_url", "qb_username", "qb_password",
    "emby_url", "emby_token",
    "integration_docker", "integration_qb", "integration_emby", "integration_ntfy",
)


@router.get("/export")
async def export_backup(_: bool = Depends(require_auth)):
    with db() as conn:
        rows = conn.execute(
            "SELECT key, value FROM settings WHERE key IN ({})".format(
                ",".join("?" * len(SETTINGS_KEYS))
            ),
            SETTINGS_KEYS,
        ).fetchall()
        settings = {r["key"]: r["value"] for r in rows}

        rules = [dict(r) for r in conn.execute(
            "SELECT rule_type, name, container, trigger, action, command, enabled "
            "FROM rules ORDER BY id"
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
    settings = payload.get("settings")
    if settings is None and version == 1:
        # v1 was a flat settings-only payload
        settings = {k: payload[k] for k in SETTINGS_KEYS if k in payload}

    with db() as conn:
        if isinstance(settings, dict):
            for k, v in settings.items():
                if k not in SETTINGS_KEYS or v in (None, ""):
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
            for r in rules:
                conn.execute(
                    "INSERT INTO rules(rule_type, name, container, trigger, action, command, enabled) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?)",
                    (
                        r.get("rule_type", "docker"),
                        r.get("name", ""),
                        r.get("container", ""),
                        r.get("trigger", "failover"),
                        r.get("action", ""),
                        r.get("command", ""),
                        1 if r.get("enabled", 1) else 0,
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

    # Refresh settings cache after bulk import
    from ..db import _load_cache  # noqa: WPS437
    _load_cache()

    log_event(
        "info",
        f"Backup restored: {counts['settings']} settings, "
        f"{counts['rules']} rules, {counts['events']} events",
    )
    return {"ok": True, "imported": counts}
