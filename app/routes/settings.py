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
    "gre_device_model",
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
        "unifi_ssh_username":       get_setting("unifi_ssh_username", "root"),
        "unifi_ssh_password_set":   bool(get_setting("unifi_ssh_password")),
        "gre_device_model":         get_setting("gre_device_model", ""),
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
    set_setting("unifi_ssh_username", payload.unifi_ssh_username.strip() or "root")
    if payload.unifi_ssh_password:
        set_setting("unifi_ssh_password", payload.unifi_ssh_password)
    set_setting("gre_device_model", payload.gre_device_model.strip().upper())
    log_event("info", "Settings updated")
    return {"ok": True}


@router.get("/debug-ssh")
async def debug_unifi_ssh(_: bool = Depends(require_auth)):
    """Return raw mca-dump + ip route output for diagnosing SSH WAN detection."""
    host     = get_setting("unifi_host", "")
    port     = int(get_setting("unifi_ssh_port", "22"))
    username = get_setting("unifi_ssh_username", "root")
    password = get_setting("unifi_ssh_password", "")
    if not (host and password):
        return JSONResponse({"ok": False, "error": "Not configured"}, status_code=400)
    from ..unifi_ssh import UniFiSSHClient
    client = UniFiSSHClient(host, port, username, password)
    result: dict = {}
    try:
        for label, cmd in [
            ("mca_dump",     "mca-dump 2>/dev/null || echo 'NOT_FOUND'"),
            ("ip_route",     "ip route show 2>/dev/null"),
            ("ip_route_all", "ip route show table all 2>/dev/null | head -40"),
            ("ip_tunnel",    "ip tunnel show 2>/dev/null"),
            ("hostname",     "hostname 2>/dev/null"),
            # ── Device discovery diagnostics ──────────────────────────────────
            ("db_mongosh",   "which mongosh 2>/dev/null && mongosh --quiet localhost/ace --eval 'db.device.find({},{model:1,name:1,mac:1,ip:1,_id:0}).forEach(d=>print(JSON.stringify(d)))' 2>/dev/null || echo 'mongosh_not_found'"),
            ("db_mongo",     "which mongo 2>/dev/null && mongo --quiet localhost/ace --eval 'db.device.find({},{model:1,name:1,mac:1,ip:1}).forEach(function(d){print(JSON.stringify(d))})' 2>/dev/null || echo 'mongo_not_found'"),
            ("db_socket",    "ls /var/run/mongodb/ /run/mongodb/ 2>/dev/null || echo 'no_mongo_socket'"),
            ("db_files",     "find /data/unifi/data/sites /mnt/data/unifi-os/unifi/data/sites -name '*.json' 2>/dev/null | head -10 || echo 'no_site_files'"),
            ("arp_table",    "ip neigh show 2>/dev/null | head -20"),
            # ── Local UniFi controller API (read-only curl) ───────────────────
            ("ctrl_api_proxy",  "curl -sk https://localhost/proxy/network/api/s/default/stat/device 2>/dev/null | head -c 3000 || echo 'proxy_path_failed'"),
            ("ctrl_api_direct", "curl -s http://127.0.0.1:8080/api/s/default/stat/device 2>/dev/null | head -c 3000 || echo 'direct_path_failed'"),
            # ── Controller filesystem: sites dir + device JSON files ──────────
            ("ctrl_fs_sites",   "ls /mnt/data/unifi-os/unifi/data/sites/ 2>/dev/null || ls /data/unifi/data/sites/ 2>/dev/null || echo 'no_sites_dir'"),
            ("ctrl_fs_devices", "find /mnt/data /data /persistent -maxdepth 8 \\( -name 'device*.json' -o -name '*devices*.json' \\) 2>/dev/null | head -10 || echo 'no_device_files'"),
            # ── ULP backup file (Strategy 3 — present on UCG-Max) ────────────────
            ("ulp_devices_file", "cat /data/ulp-go/ws/backup_unifi_devices.json 2>/dev/null | head -c 6000 || echo 'ulp_file_not_found'"),
        ]:
            try:
                result[label] = await client.run_raw(cmd)
            except Exception as e:
                result[label] = f"ERROR: {e}"
        # ── GRE probe: SSH into each tunnel remote via the gateway as jump host ──
        try:
            gre_remotes = await client._get_gre_remotes()
            probe_results: dict = {}
            for iface, remote_ip in gre_remotes.items():
                probe_info: dict = {"ip": remote_ip}
                # Port scan: find which TCP ports are open on the remote device
                try:
                    scan_out = await client.run_raw(
                        f"for p in 22 222 2222 22022 22222 8022; do "
                        f"(echo >/dev/tcp/{remote_ip}/$p) 2>/dev/null "
                        f"&& echo \"OPEN:$p\" || echo \"CLOSED:$p\"; "
                        f"done 2>/dev/null"
                    )
                    probe_info["port_scan"] = scan_out or "(no output)"
                except Exception as pse:
                    probe_info["port_scan"] = f"ERROR: {pse}"
                # Strategy 1 raw: run ssh client on the gateway shell directly
                # so we can see the exact output / error for diagnosis.
                try:
                    shell_out = await client.run_raw(
                        f"ssh -o StrictHostKeyChecking=no "
                        f"-o ConnectTimeout=5 "
                        f"-o BatchMode=yes "
                        f"-p {port} "
                        f'{username}@{remote_ip} '
                        f'"cat /proc/ubnthal/system_info 2>/dev/null; '
                        f'echo ---HOSTNAME---; hostname 2>/dev/null" 2>&1'
                    )
                    probe_info["shell_ssh_raw"] = shell_out or "(empty output)"
                except Exception as se:
                    probe_info["shell_ssh_raw"] = f"ERROR: {se}"
                # Full probe (Strategy 1 then Strategy 2)
                try:
                    probe = await client._probe_device_at(remote_ip)
                    probe_info.update(probe)
                except Exception as pe:
                    probe_info["probe_error"] = str(pe)
                probe_results[iface] = probe_info
            result["gre_probes"] = probe_results
        except Exception as ge:
            result["gre_probes"] = {"error": str(ge)}
        return {"ok": True, "results": result}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        await client.close()


@router.post("/test-ssh")
async def test_unifi_ssh(_: bool = Depends(require_auth)):
    host     = get_setting("unifi_host", "")
    port     = int(get_setting("unifi_ssh_port", "22"))
    username = get_setting("unifi_ssh_username", "root")
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
        # Discover WAN interfaces from mca-dump so the UI can populate the drag area
        discovered = await client.discover_wans()
        return {
            "ok":             True,
            "message":        msg,
            "discovered_wans": discovered,
        }
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
