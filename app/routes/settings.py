"""Application settings: read, write, export."""
import json

from fastapi import APIRouter, Depends, Response

from ..auth import require_auth
from ..config import POLL_INTERVAL_DEFAULT
from ..db import get_setting, log_event, set_setting
from ..models import SettingsIn

router = APIRouter(prefix="/api/settings")

EXPORT_KEYS = (
    "unifi_host", "unifi_api_key", "unifi_site",
    "primary_wan", "failover_wan",
    "primary_wan_name", "failover_wan_name",
    "poll_interval", "event_retention_days",
    "latency_threshold_ms", "latency_cooldown_min",
    "ntfy_url", "ntfy_topic", "ntfy_token",
    "ntfy_on_failover", "ntfy_on_restored", "ntfy_on_high_latency", "ntfy_on_error",
    "qb_url", "qb_username", "qb_password",
    "emby_url", "emby_token",
    "integration_docker", "integration_qb", "integration_emby", "integration_ntfy",
)


@router.get("")
async def get_settings(_: bool = Depends(require_auth)):
    return {
        "unifi_host":           get_setting("unifi_host", ""),
        "unifi_api_key_set":    bool(get_setting("unifi_api_key")),
        "unifi_site":           get_setting("unifi_site", "default"),
        "primary_wan":          get_setting("primary_wan", "wan"),
        "failover_wan":         get_setting("failover_wan", "wan2"),
        "primary_wan_name":     get_setting("primary_wan_name", ""),
        "failover_wan_name":    get_setting("failover_wan_name", ""),
        "poll_interval":        int(get_setting("poll_interval", str(POLL_INTERVAL_DEFAULT))),
        "event_retention_days": int(get_setting("event_retention_days", "30")),
        "latency_threshold_ms": int(get_setting("latency_threshold_ms", "0")),
        "latency_cooldown_min": int(get_setting("latency_cooldown_min", "5")),
    }


@router.post("")
async def save_settings(payload: SettingsIn, _: bool = Depends(require_auth)):
    set_setting("unifi_host",          payload.unifi_host.strip())
    if payload.unifi_api_key:
        set_setting("unifi_api_key",   payload.unifi_api_key.strip())
    set_setting("unifi_site",          payload.unifi_site.strip() or "default")
    set_setting("primary_wan",         payload.primary_wan.strip())
    set_setting("failover_wan",        payload.failover_wan.strip())
    set_setting("primary_wan_name",    payload.primary_wan_name.strip())
    set_setting("failover_wan_name",   payload.failover_wan_name.strip())
    set_setting("poll_interval",        str(max(5, payload.poll_interval)))
    set_setting("event_retention_days", str(max(1, payload.event_retention_days)))
    set_setting("latency_threshold_ms", str(max(0, payload.latency_threshold_ms)))
    set_setting("latency_cooldown_min", str(max(1, payload.latency_cooldown_min)))
    log_event("info", "Settings updated")
    return {"ok": True}


@router.get("/export")
async def export_settings(_: bool = Depends(require_auth)):
    data = {"wanifi_export_version": 1}
    for k in EXPORT_KEYS:
        data[k] = get_setting(k, "")
    return Response(
        content=json.dumps(data, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=wanifi-settings.json"},
    )
