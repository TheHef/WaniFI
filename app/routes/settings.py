"""Application settings: read, write, export."""
import json

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from ..auth import require_auth
from ..config import POLL_INTERVAL_DEFAULT
from ..db import get_setting, log_event, set_setting
from ..models import SettingsIn

router = APIRouter(prefix="/api/settings")

EXPORT_KEYS = (
    "router_type",
    "unifi_host", "unifi_api_key", "unifi_site",
    "unifi_ssh_mode", "unifi_ssh_port", "unifi_ssh_username", "unifi_ssh_password",
    "primary_wan", "failover_wan",
    "openwrt_url", "openwrt_username", "openwrt_password",
    "openwrt_primary_iface", "openwrt_failover_iface", "openwrt_router_model",
    "primary_wan_name", "failover_wan_name",
    "poll_interval", "event_retention_days",
    "latency_threshold_ms", "latency_cooldown_min",
    "ntfy_url", "ntfy_topic", "ntfy_token",
    "ntfy_on_failover", "ntfy_on_restored", "ntfy_on_high_latency", "ntfy_on_error",
    "discord_webhook_url",
    "telegram_bot_token", "telegram_chat_id",
    "pushover_app_token", "pushover_user_key",
    "qb_url", "qb_username", "qb_password",
    "sabnzbd_url", "sabnzbd_api_key",
    "transmission_url", "transmission_username", "transmission_password",
    "deluge_url", "deluge_password",
    "emby_url", "emby_token",
    "jellyfin_url", "jellyfin_token",
    "plex_url", "plex_token",
    "ha_url", "ha_token",
    "proxmox_url", "proxmox_username", "proxmox_password", "proxmox_node",
    "sonarr_url", "sonarr_api_key",
    "radarr_url", "radarr_api_key",
    "pihole_url", "pihole_token",
    "adguard_url", "adguard_username", "adguard_password",
    "portainer_url", "portainer_token", "portainer_env_id",
    "truenas_url", "truenas_api_key",
    "unraid_url", "unraid_api_key",
    "nodered_url", "nodered_username", "nodered_password",
    "gotify_url", "gotify_token",
    "gotify_on_failover", "gotify_on_restored", "gotify_on_error", "gotify_on_high_latency",
    "nzbget_url", "nzbget_username", "nzbget_password",
    "npm_url", "npm_username", "npm_password",
    "cloudflare_zone_id", "cloudflare_api_token",
    "nut_host", "nut_port", "nut_ups_name", "nut_username", "nut_password",
    "integration_host_command", "integration_docker", "integration_webhook",
    "integration_qb", "integration_sabnzbd", "integration_transmission", "integration_deluge",
    "integration_emby", "integration_jellyfin", "integration_plex",
    "integration_ntfy", "integration_discord", "integration_telegram", "integration_pushover",
    "integration_homeassistant", "integration_proxmox", "integration_sonarr", "integration_radarr",
    "integration_pihole", "integration_adguard",
    "integration_portainer", "integration_truenas", "integration_unraid",
    "integration_nodered", "integration_nzbget", "integration_gotify",
    "speedtest_server_id", "speedtest_server_name", "speedtest_source_ip",
    "integration_speedtest", "integration_npm", "integration_cloudflare", "integration_nut",
)


@router.get("")
async def get_settings(_: bool = Depends(require_auth)):
    return {
        "router_type":              get_setting("router_type", "unifi"),
        "unifi_host":               get_setting("unifi_host", ""),
        "unifi_api_key_set":        bool(get_setting("unifi_api_key")),
        "unifi_site":               get_setting("unifi_site", "default"),
        "primary_wan":              get_setting("primary_wan", "wan"),
        "failover_wan":             get_setting("failover_wan", "wan2"),
        "primary_wan_name":         get_setting("primary_wan_name", ""),
        "failover_wan_name":        get_setting("failover_wan_name", ""),
        "poll_interval":            int(get_setting("poll_interval", str(POLL_INTERVAL_DEFAULT))),
        "event_retention_days":     int(get_setting("event_retention_days", "30")),
        "latency_threshold_ms":     int(get_setting("latency_threshold_ms", "0")),
        "latency_cooldown_min":     int(get_setting("latency_cooldown_min", "5")),
        "unifi_ssh_mode":           get_setting("unifi_ssh_mode", "0") == "1",
        "unifi_ssh_port":           int(get_setting("unifi_ssh_port", "22")),
        "unifi_ssh_username":       get_setting("unifi_ssh_username", "admin"),
        "unifi_ssh_password_set":   bool(get_setting("unifi_ssh_password")),
    }


@router.post("")
async def save_settings(payload: SettingsIn, _: bool = Depends(require_auth)):
    rtype = payload.router_type.strip() if payload.router_type in ("unifi", "openwrt", "glinet") else "unifi"
    set_setting("router_type",         rtype)
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
    set_setting("unifi_ssh_mode",     "1" if payload.unifi_ssh_mode else "0")
    set_setting("unifi_ssh_port",     str(max(1, min(65535, payload.unifi_ssh_port))))
    set_setting("unifi_ssh_username", payload.unifi_ssh_username.strip() or "admin")
    if payload.unifi_ssh_password:
        set_setting("unifi_ssh_password", payload.unifi_ssh_password)
    log_event("info", "Settings updated")
    return {"ok": True}


@router.post("/test-ssh")
async def test_unifi_ssh(_: bool = Depends(require_auth)):
    host     = get_setting("unifi_host", "")
    port     = int(get_setting("unifi_ssh_port", "22"))
    username = get_setting("unifi_ssh_username", "admin")
    password = get_setting("unifi_ssh_password", "")
    if not host:
        return JSONResponse({"ok": False, "error": "No UniFi host configured"}, status_code=400)
    if not password:
        return JSONResponse({"ok": False, "error": "No SSH password saved — enter and save first"}, status_code=400)
    from ..unifi_ssh import UniFiSSHClient
    client = UniFiSSHClient(host, port, username, password)
    try:
        ok, msg = await client.test_connection()
        if not ok:
            return JSONResponse({"ok": False, "error": msg}, status_code=400)
        return {"ok": True, "message": msg}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        await client.close()


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
