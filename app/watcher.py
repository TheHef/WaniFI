"""Background loops that poll the UniFi controller and fire automation rules."""
import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Optional

from .config import (
    LIVE_INTERVAL,
    METRICS_WRITE_INTERVAL,
    POLL_INTERVAL_DEFAULT,
    log,
)
from .db import (
    a_log_event,
    a_set_state,
    a_write_metric,
    db,
    get_setting,
    get_state,
    purge_old_events,
)
from .docker_ops import container_action
from .notify import send_notification
from .unifi import UniFiClient

_bg_tasks: set[asyncio.Task] = set()


def _create_task(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    t.add_done_callback(lambda task: log.warning("Background task failed: %s", task.exception()) if not task.cancelled() and task.exception() else None)
    return t


class WatcherState:
    def __init__(self):
        self.task:  Optional[asyncio.Task] = None
        self.live_task: Optional[asyncio.Task] = None
        self.current_wan:     Optional[str] = None
        self.last_check:      Optional[str] = None
        self.last_error:      Optional[str] = None
        self.state_changed_at: Optional[str] = None
        self.live_gw_info: dict = {}
        self.latency_last_fired: float = 0.0


state = WatcherState()


def determine_active_wan(
    wans: list[dict],
    primary_name: str,
    failover_name: str,
    gateway_info: Optional[dict] = None,
) -> str:
    """Resolve the active WAN by uplink comment, then uptime stats, then health status."""
    if gateway_info:
        comment = gateway_info.get("active_wan", "").upper()
        if comment:
            if comment == primary_name.upper():  return "primary"
            if comment == failover_name.upper(): return "failover"

    wan_health = next((w for w in wans if w.get("subsystem") == "wan"), None)
    if wan_health:
        stats = wan_health.get("uptime_stats", {})
        p_avail = stats.get(primary_name.upper(),  {}).get("availability")
        f_avail = stats.get(failover_name.upper(), {}).get("availability")
        if p_avail == 0.0 and f_avail is not None and f_avail > 0:
            return "failover"
        if p_avail is not None and p_avail > 0:
            return "primary"

    by_name: dict = {}
    for w in wans:
        for k in ("ifname", "gw_name", "name", "subsystem"):
            v = w.get(k)
            if v:
                by_name[str(v).lower()] = w
    if (p := by_name.get(primary_name.lower())) and p.get("status") == "ok":
        return "primary"
    if (f := by_name.get(failover_name.lower())) and f.get("status") == "ok":
        return "failover"
    return "down"


async def execute_host_command(command: str, timeout: int = 30) -> tuple[bool, str]:
    """Execute a shell command in the host's namespaces via nsenter."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "nsenter", "--target", "1",
            "--mount", "--uts", "--ipc", "--net", "--pid",
            "--", "/bin/sh", "-c", command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return False, f"Timed out after {timeout}s"
        out = (stdout or b"").decode().strip()
        err = (stderr or b"").decode().strip()
        if proc.returncode == 0:
            return True, out or "ok"
        return False, err or f"exit code {proc.returncode}"
    except FileNotFoundError:
        return False, "nsenter not found — container needs --pid=host and --privileged"
    except Exception as e:
        return False, str(e)


async def run_qb_action(action: str, value: str = "") -> tuple[bool, str]:
    from .qbittorrent import QBittorrentClient
    url  = get_setting("qb_url", "")
    user = get_setting("qb_username", "")
    pw   = get_setting("qb_password", "")
    if not (url and user):
        return False, "qBittorrent not configured"
    client = QBittorrentClient(url, user, pw or "")
    try:
        ok, err = await client.login()
        if not ok:
            return False, f"qB login failed: {err}"
        if action == "alt_speed_on":
            return await client.set_alt_speed(True)
        if action == "alt_speed_off":
            return await client.set_alt_speed(False)
        if action == "set_dl_limit":
            return await client.set_download_limit(int(value) if value else 0)
        if action == "set_ul_limit":
            return await client.set_upload_limit(int(value) if value else 0)
        if action == "pause_all":
            return await client.pause_all()
        if action == "resume_all":
            return await client.resume_all()
        return False, f"Unknown qB action: {action}"
    finally:
        await client.close()


async def run_emby_action(action: str, value: str = "") -> tuple[bool, str]:
    from .emby import EmbyClient
    url   = get_setting("emby_url", "")
    token = get_setting("emby_token", "")
    if not (url and token):
        return False, "Emby not configured"
    client = EmbyClient(url, token)
    try:
        if action == "set_bitrate_limit":
            return await client.set_bitrate_limit(int(value) if value else 0)
        if action == "set_bitrate_and_restream":
            try:
                mbps = int(value) if value else 0
            except (ValueError, TypeError):
                mbps = 0
            return await client.set_bitrate_and_restream(mbps)
        if action == "clear_bitrate_limit":
            return await client.clear_bitrate_limit()
        if action == "stop_all_sessions":
            return await client.stop_all_sessions()
        return False, f"Unknown Emby action: {action}"
    finally:
        await client.close()


async def run_jellyfin_action(action: str, value: str = "") -> tuple[bool, str]:
    from .jellyfin import JellyfinClient
    url   = get_setting("jellyfin_url", "")
    token = get_setting("jellyfin_token", "")
    if not (url and token):
        return False, "Jellyfin not configured"
    client = JellyfinClient(url, token)
    try:
        if action == "set_bitrate_limit":
            return await client.set_bitrate_limit(int(value) if value else 0)
        if action == "set_bitrate_and_restream":
            try:
                mbps = int(value) if value else 0
            except (ValueError, TypeError):
                mbps = 0
            return await client.set_bitrate_and_restream(mbps)
        if action == "clear_bitrate_limit":
            return await client.clear_bitrate_limit()
        if action == "stop_all_sessions":
            return await client.stop_all_sessions()
        return False, f"Unknown Jellyfin action: {action}"
    finally:
        await client.close()


async def run_plex_action(action: str, value: str = "") -> tuple[bool, str]:
    from .plex import PlexClient
    url   = get_setting("plex_url", "")
    token = get_setting("plex_token", "")
    if not (url and token):
        return False, "Plex not configured"
    client = PlexClient(url, token)
    try:
        if action == "set_wan_bitrate":
            return await client.set_wan_bitrate(int(value) if value else 0)
        if action == "clear_wan_bitrate":
            return await client.clear_wan_bitrate()
        if action == "stop_all_streams":
            return await client.stop_all_streams()
        return False, f"Unknown Plex action: {action}"
    finally:
        await client.close()


async def run_sabnzbd_action(action: str, value: str = "") -> tuple[bool, str]:
    from .sabnzbd import SabnzbdClient
    url     = get_setting("sabnzbd_url", "")
    api_key = get_setting("sabnzbd_api_key", "")
    if not (url and api_key):
        return False, "SABnzbd not configured"
    client = SabnzbdClient(url, api_key)
    try:
        if action == "pause":
            return await client.pause()
        if action == "resume":
            return await client.resume()
        if action == "set_speed_limit":
            try:
                limit = int(value) if value else 100
            except (ValueError, TypeError):
                limit = 100
            return await client.set_speed_limit(limit)
        return False, f"Unknown SABnzbd action: {action}"
    finally:
        await client.close()


async def run_transmission_action(action: str, value: str = "") -> tuple[bool, str]:
    from .transmission import TransmissionClient
    url  = get_setting("transmission_url", "")
    user = get_setting("transmission_username", "")
    pw   = get_setting("transmission_password", "")
    if not url:
        return False, "Transmission not configured"
    client = TransmissionClient(url, user, pw or "")
    try:
        if action == "pause_all":
            return await client.pause_all()
        if action == "resume_all":
            return await client.resume_all()
        if action == "alt_speed_on":
            return await client.set_alt_speed(True)
        if action == "alt_speed_off":
            return await client.set_alt_speed(False)
        if action == "set_dl_limit":
            try:
                limit = int(value) if value else 0
            except (ValueError, TypeError):
                limit = 0
            return await client.set_dl_limit(limit)
        if action == "set_ul_limit":
            try:
                limit = int(value) if value else 0
            except (ValueError, TypeError):
                limit = 0
            return await client.set_ul_limit(limit)
        return False, f"Unknown Transmission action: {action}"
    finally:
        await client.close()


async def run_deluge_action(action: str, value: str = "") -> tuple[bool, str]:
    from .deluge import DelugeClient
    url = get_setting("deluge_url", "")
    pw  = get_setting("deluge_password", "")
    if not url:
        return False, "Deluge not configured"
    client = DelugeClient(url, pw or "")
    ok, err = await client.login()
    if not ok:
        return False, f"Deluge login failed: {err}"
    try:
        if action == "pause_all":
            return await client.pause_all()
        if action == "resume_all":
            return await client.resume_all()
        if action == "set_dl_limit":
            try:
                limit = int(value) if value else 0
            except (ValueError, TypeError):
                limit = 0
            return await client.set_dl_limit(limit)
        if action == "set_ul_limit":
            try:
                limit = int(value) if value else 0
            except (ValueError, TypeError):
                limit = 0
            return await client.set_ul_limit(limit)
        return False, f"Unknown Deluge action: {action}"
    finally:
        await client.close()


async def run_ha_action(action: str, value: str = "") -> tuple[bool, str]:
    from .homeassistant import HomeAssistantClient
    url   = get_setting("ha_url", "")
    token = get_setting("ha_token", "")
    if not (url and token):
        return False, "Home Assistant not configured"
    client = HomeAssistantClient(url, token)
    try:
        if action == "call_webhook":
            return await client.trigger_webhook(value)
        if action == "turn_on":
            return await client.call_service("homeassistant", "turn_on", value)
        if action == "turn_off":
            return await client.call_service("homeassistant", "turn_off", value)
        return False, f"Unknown HA action: {action}"
    finally:
        await client.close()


async def run_proxmox_action(action: str, value: str = "") -> tuple[bool, str]:
    from .proxmox import ProxmoxClient
    url  = get_setting("proxmox_url", "")
    user = get_setting("proxmox_username", "")
    pw   = get_setting("proxmox_password", "")
    node = get_setting("proxmox_node", "pve")
    if not (url and user):
        return False, "Proxmox not configured"
    # value format: "node/vmid" or just "vmid" (uses default node)
    parts = value.split("/", 1) if "/" in value else [node, value]
    vm_node = parts[0] if len(parts) == 2 else node
    vmid    = parts[1] if len(parts) == 2 else parts[0]
    action_map = {
        "stop_vm":     "stop",
        "shutdown_vm": "shutdown",
        "suspend_vm":  "suspend",
        "resume_vm":   "resume",
        "start_vm":    "start",
    }
    proxmox_action = action_map.get(action)
    if not proxmox_action:
        return False, f"Unknown Proxmox action: {action}"
    client = ProxmoxClient(url, user, pw or "", node)
    try:
        return await client.vm_action(vm_node, vmid, proxmox_action)
    finally:
        await client.close()


async def run_sonarr_action(action: str) -> tuple[bool, str]:
    from .sonarr import SonarrClient
    url     = get_setting("sonarr_url", "")
    api_key = get_setting("sonarr_api_key", "")
    if not (url and api_key):
        return False, "Sonarr not configured"
    client = SonarrClient(url, api_key)
    try:
        if action == "disable_indexers":
            return await client.set_indexers_enabled(False)
        if action == "enable_indexers":
            return await client.set_indexers_enabled(True)
        if action == "disable_download_clients":
            return await client.set_download_clients_enabled(False)
        if action == "enable_download_clients":
            return await client.set_download_clients_enabled(True)
        if action == "search_missing":
            return await client.search_missing()
        if action == "refresh_all":
            return await client.refresh_all()
        return False, f"Unknown Sonarr action: {action}"
    finally:
        await client.close()


async def run_radarr_action(action: str) -> tuple[bool, str]:
    from .radarr import RadarrClient
    url     = get_setting("radarr_url", "")
    api_key = get_setting("radarr_api_key", "")
    if not (url and api_key):
        return False, "Radarr not configured"
    client = RadarrClient(url, api_key)
    try:
        if action == "disable_indexers":
            return await client.set_indexers_enabled(False)
        if action == "enable_indexers":
            return await client.set_indexers_enabled(True)
        if action == "disable_download_clients":
            return await client.set_download_clients_enabled(False)
        if action == "enable_download_clients":
            return await client.set_download_clients_enabled(True)
        if action == "search_missing":
            return await client.search_missing()
        if action == "refresh_all":
            return await client.refresh_all()
        return False, f"Unknown Radarr action: {action}"
    finally:
        await client.close()



async def run_pihole_action(action: str) -> tuple[bool, str]:
    from .pihole import PiholeClient
    url   = get_setting("pihole_url", "")
    token = get_setting("pihole_token", "")
    if not url:
        return False, "Pi-hole not configured"
    client = PiholeClient(url, token or "")
    try:
        if action == "enable":
            return await client.enable()
        if action == "disable":
            return await client.disable()
        return False, f"Unknown Pi-hole action: {action}"
    finally:
        await client.close()


async def run_adguard_action(action: str) -> tuple[bool, str]:
    from .adguard import AdGuardClient
    url  = get_setting("adguard_url", "")
    user = get_setting("adguard_username", "")
    pw   = get_setting("adguard_password", "")
    if not url:
        return False, "AdGuard not configured"
    client = AdGuardClient(url, user, pw or "")
    try:
        if action == "enable_protection":
            return await client.set_protection(True)
        if action == "disable_protection":
            return await client.set_protection(False)
        return False, f"Unknown AdGuard action: {action}"
    finally:
        await client.close()


async def run_portainer_action(action: str, container_name: str = "") -> tuple[bool, str]:
    from .portainer import PortainerClient
    url    = get_setting("portainer_url", "")
    token  = get_setting("portainer_token", "")
    env_id = get_setting("portainer_env_id", "1")
    if not (url and token):
        return False, "Portainer not configured"
    client = PortainerClient(url, token, env_id)
    act_map = {
        "start_container":   "start",
        "stop_container":    "stop",
        "restart_container": "restart",
    }
    docker_action = act_map.get(action)
    if not docker_action:
        return False, f"Unknown Portainer action: {action}"
    try:
        return await client.container_action(container_name, docker_action)
    finally:
        await client.close()


async def run_truenas_action(action: str, service: str = "") -> tuple[bool, str]:
    from .truenas import TrueNASClient
    url     = get_setting("truenas_url", "")
    api_key = get_setting("truenas_api_key", "")
    if not (url and api_key):
        return False, "TrueNAS not configured"
    client = TrueNASClient(url, api_key)
    act_map = {
        "start_service":   "start",
        "stop_service":    "stop",
        "restart_service": "restart",
    }
    truenas_action = act_map.get(action)
    if not truenas_action:
        return False, f"Unknown TrueNAS action: {action}"
    try:
        return await client.service_action(service, truenas_action)
    finally:
        await client.close()


async def run_unraid_action(action: str, vm_name: str = "") -> tuple[bool, str]:
    from .unraid import UnraidClient
    url     = get_setting("unraid_url", "")
    api_key = get_setting("unraid_api_key", "")
    if not (url and api_key):
        return False, "Unraid not configured"
    client = UnraidClient(url, api_key)
    act_map = {
        "start_vm":  "start",
        "stop_vm":   "stop",
        "pause_vm":  "pause",
        "resume_vm": "resume",
    }
    vm_action = act_map.get(action)
    if not vm_action:
        return False, f"Unknown Unraid action: {action}"
    try:
        return await client.vm_action(vm_name, vm_action)
    finally:
        await client.close()


async def run_nodered_action(action: str, endpoint: str = "") -> tuple[bool, str]:
    from .nodered import NodeRedClient
    url  = get_setting("nodered_url", "")
    user = get_setting("nodered_username", "")
    pw   = get_setting("nodered_password", "")
    if not url:
        return False, "Node-RED not configured"
    client = NodeRedClient(url, user, pw or "")
    try:
        if action == "trigger_flow":
            return await client.trigger_flow(endpoint)
        return False, f"Unknown Node-RED action: {action}"
    finally:
        await client.close()


async def run_nzbget_action(action: str, value: str = "") -> tuple[bool, str]:
    from .nzbget import NZBGetClient
    url  = get_setting("nzbget_url", "")
    user = get_setting("nzbget_username", "")
    pw   = get_setting("nzbget_password", "")
    if not url:
        return False, "NZBGet not configured"
    client = NZBGetClient(url, user, pw or "")
    try:
        if action == "pause":
            return await client.pause()
        if action == "resume":
            return await client.resume()
        if action == "set_speed_limit":
            try:
                limit = int(value) if value else 0
            except (ValueError, TypeError):
                limit = 0
            return await client.set_speed_limit(limit)
        return False, f"Unknown NZBGet action: {action}"
    finally:
        await client.close()


async def run_speedtest_action() -> tuple[bool, str]:
    from .speedtest_runner import run_speedtest
    return await run_speedtest()


async def run_npm_action(action: str, value: str = "") -> tuple[bool, str]:
    from .npm_client import NpmClient
    url  = get_setting("npm_url", "")
    user = get_setting("npm_username", "")
    pw   = get_setting("npm_password", "")
    if not (url and user):
        return False, "NPM not configured"
    client = NpmClient(url, user, pw or "")
    try:
        if action == "enable_host":
            if not value:
                return False, "Host name/ID required"
            return await client.set_host_enabled(value, True)
        if action == "disable_host":
            if not value:
                return False, "Host name/ID required"
            return await client.set_host_enabled(value, False)
        return False, f"Unknown NPM action: {action}"
    finally:
        await client.close()


async def run_cloudflare_action(action: str) -> tuple[bool, str]:
    from .cloudflare import CloudflareClient
    token   = get_setting("cloudflare_api_token", "")
    zone_id = get_setting("cloudflare_zone_id", "")
    if not (token and zone_id):
        return False, "Cloudflare not configured"
    client = CloudflareClient(token, zone_id)
    try:
        if action == "enable_under_attack":
            return await client.enable_under_attack()
        if action == "disable_under_attack":
            return await client.disable_under_attack()
        if action == "purge_cache":
            return await client.purge_cache()
        if action == "enable_dev_mode":
            return await client.set_development_mode(True)
        if action == "disable_dev_mode":
            return await client.set_development_mode(False)
        return False, f"Unknown Cloudflare action: {action}"
    finally:
        await client.close()


async def run_nut_action(action: str) -> tuple[bool, str]:
    from .nut import NutClient
    host     = get_setting("nut_host", "")
    port     = int(get_setting("nut_port", "3493"))
    ups_name = get_setting("nut_ups_name", "ups")
    username = get_setting("nut_username", "")
    password = get_setting("nut_password", "")
    if not host:
        return False, "NUT not configured"
    client = NutClient(host, port, ups_name, username, password or "")
    if action == "get_status":
        return await client.get_status()
    if action == "beeper_enable":
        return await client.instcmd("beeper.enable")
    if action == "beeper_disable":
        return await client.instcmd("beeper.disable")
    if action == "shutdown_return":
        return await client.instcmd("shutdown.return")
    if action == "shutdown_stayoff":
        return await client.instcmd("shutdown.stayoff")
    if action == "load_off":
        return await client.instcmd("load.off")
    return False, f"Unknown NUT action: {action}"


async def run_unifi_rule_action(action: str, value: str = "") -> tuple[bool, str]:
    """Run a UniFi-specific rule action using the globally configured UniFi credentials."""
    host    = get_setting("unifi_host", "")
    api_key = get_setting("unifi_api_key", "")
    site    = get_setting("unifi_site", "default")
    if not host or not api_key:
        return False, "UniFi not configured (host/API key missing)"
    client = UniFiClient(host, api_key, site)
    try:
        if action == "kick_all_clients":
            return await client.kick_all_clients()
        if action == "disable_wlan":
            if not value:
                return False, "WLAN name required"
            return await client.set_wlan_enabled(value, False)
        if action == "enable_wlan":
            if not value:
                return False, "WLAN name required"
            return await client.set_wlan_enabled(value, True)
        if action == "block_client":
            if not value:
                return False, "MAC address required"
            return await client.set_client_blocked(value, True)
        if action == "unblock_client":
            if not value:
                return False, "MAC address required"
            return await client.set_client_blocked(value, False)
        return False, f"Unknown UniFi action: {action}"
    finally:
        await client.close()


async def run_webhook_action(url: str, method: str = "POST") -> tuple[bool, str]:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10, verify=False) as client:
            r = await getattr(client, method.lower())(url)
            return r.status_code < 400, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)


async def fire_trigger(trigger: str):
    with db() as conn:
        rules = conn.execute(
            "SELECT * FROM rules WHERE enabled=1 AND trigger=?", (trigger,)
        ).fetchall()
    if not rules:
        return
    for rule in rules:
        rtype = rule["rule_type"]

        # Skip if integration is disabled
        integration_key = {
            "docker":        "integration_docker",
            "host_command":  "integration_host_command",
            "qbittorrent":   "integration_qb",
            "sabnzbd":       "integration_sabnzbd",
            "transmission":  "integration_transmission",
            "deluge":        "integration_deluge",
            "emby":          "integration_emby",
            "jellyfin":      "integration_jellyfin",
            "plex":          "integration_plex",
            "homeassistant": "integration_homeassistant",
            "proxmox":       "integration_proxmox",
            "sonarr":        "integration_sonarr",
            "radarr":        "integration_radarr",
            "pihole":        "integration_pihole",
            "adguard":       "integration_adguard",
            "portainer":     "integration_portainer",
            "truenas":       "integration_truenas",
            "unraid":        "integration_unraid",
            "nodered":       "integration_nodered",
            "nzbget":        "integration_nzbget",
            "speedtest":     "integration_speedtest",
            "npm":           "integration_npm",
            "cloudflare":    "integration_cloudflare",
            "nut":           "integration_nut",
            # unifi_rule reuses the global UniFi credentials — no separate toggle
        }.get(rtype)
        if integration_key and get_setting(integration_key, "0") != "1":
            await a_log_event("info", f"Rule '{rule['name']}' skipped (integration disabled)")
            continue

        # Optional delay before executing
        delay = rule["delay_seconds"] if "delay_seconds" in rule.keys() else 0
        if delay and delay > 0:
            await asyncio.sleep(delay)

        if rtype == "host_command":
            ok, msg = await execute_host_command(rule["command"])
            await a_log_event(
                "info" if ok else "error",
                f"Rule: host `{rule['command']}` on {trigger} -> {msg}",
            )
        elif rtype == "qbittorrent":
            ok, msg = await run_qb_action(rule["action"], rule["container"])
            await a_log_event(
                "info" if ok else "error",
                f"Rule: qB {rule['action']} on {trigger} -> {msg}",
            )
        elif rtype == "sabnzbd":
            ok, msg = await run_sabnzbd_action(rule["action"], rule["container"])
            await a_log_event(
                "info" if ok else "error",
                f"Rule: SABnzbd {rule['action']} on {trigger} -> {msg}",
            )
        elif rtype == "transmission":
            ok, msg = await run_transmission_action(rule["action"], rule["container"])
            await a_log_event(
                "info" if ok else "error",
                f"Rule: Transmission {rule['action']} on {trigger} -> {msg}",
            )
        elif rtype == "deluge":
            ok, msg = await run_deluge_action(rule["action"], rule["container"])
            await a_log_event(
                "info" if ok else "error",
                f"Rule: Deluge {rule['action']} on {trigger} -> {msg}",
            )
        elif rtype == "emby":
            ok, msg = await run_emby_action(rule["action"], rule["container"])
            await a_log_event(
                "info" if ok else "error",
                f"Rule: Emby {rule['action']} on {trigger} -> {msg}",
            )
        elif rtype == "jellyfin":
            ok, msg = await run_jellyfin_action(rule["action"], rule["container"])
            await a_log_event(
                "info" if ok else "error",
                f"Rule: Jellyfin {rule['action']} on {trigger} -> {msg}",
            )
        elif rtype == "plex":
            ok, msg = await run_plex_action(rule["action"], rule["container"])
            await a_log_event(
                "info" if ok else "error",
                f"Rule: Plex {rule['action']} on {trigger} -> {msg}",
            )
        elif rtype == "homeassistant":
            ok, msg = await run_ha_action(rule["action"], rule["container"])
            await a_log_event(
                "info" if ok else "error",
                f"Rule: HA {rule['action']} on {trigger} -> {msg}",
            )
        elif rtype == "proxmox":
            ok, msg = await run_proxmox_action(rule["action"], rule["container"])
            await a_log_event(
                "info" if ok else "error",
                f"Rule: Proxmox {rule['action']} on {trigger} -> {msg}",
            )
        elif rtype == "sonarr":
            ok, msg = await run_sonarr_action(rule["action"])
            await a_log_event(
                "info" if ok else "error",
                f"Rule: Sonarr {rule['action']} on {trigger} -> {msg}",
            )
        elif rtype == "radarr":
            ok, msg = await run_radarr_action(rule["action"])
            await a_log_event(
                "info" if ok else "error",
                f"Rule: Radarr {rule['action']} on {trigger} -> {msg}",
            )
        elif rtype == "webhook":
            method = rule["container"] or "POST"
            ok, msg = await run_webhook_action(rule["command"], method)
            await a_log_event(
                "info" if ok else "error",
                f"Rule: webhook {method} {rule['command']} on {trigger} -> {msg}",
            )
        elif rtype == "pihole":
            ok, msg = await run_pihole_action(rule["action"])
            await a_log_event("info" if ok else "error", f"Rule: Pi-hole {rule['action']} on {trigger} -> {msg}")
        elif rtype == "adguard":
            ok, msg = await run_adguard_action(rule["action"])
            await a_log_event("info" if ok else "error", f"Rule: AdGuard {rule['action']} on {trigger} -> {msg}")
        elif rtype == "portainer":
            ok, msg = await run_portainer_action(rule["action"], rule["container"])
            await a_log_event("info" if ok else "error", f"Rule: Portainer {rule['action']} on {trigger} -> {msg}")
        elif rtype == "truenas":
            ok, msg = await run_truenas_action(rule["action"], rule["container"])
            await a_log_event("info" if ok else "error", f"Rule: TrueNAS {rule['action']} on {trigger} -> {msg}")
        elif rtype == "unraid":
            ok, msg = await run_unraid_action(rule["action"], rule["container"])
            await a_log_event("info" if ok else "error", f"Rule: Unraid {rule['action']} on {trigger} -> {msg}")
        elif rtype == "nodered":
            ok, msg = await run_nodered_action(rule["action"], rule["command"])
            await a_log_event("info" if ok else "error", f"Rule: Node-RED {rule['action']} on {trigger} -> {msg}")
        elif rtype == "nzbget":
            ok, msg = await run_nzbget_action(rule["action"], rule["container"])
            await a_log_event("info" if ok else "error", f"Rule: NZBGet {rule['action']} on {trigger} -> {msg}")
        elif rtype == "unifi_rule":
            ok, msg = await run_unifi_rule_action(rule["action"], rule["container"])
            await a_log_event("info" if ok else "error", f"Rule: UniFi {rule['action']} on {trigger} -> {msg}")
        elif rtype == "speedtest":
            ok, msg = await run_speedtest_action()
            await a_log_event("info" if ok else "error", f"Rule: Speedtest on {trigger} -> {msg}")
        elif rtype == "npm":
            ok, msg = await run_npm_action(rule["action"], rule["container"])
            await a_log_event("info" if ok else "error", f"Rule: NPM {rule['action']} on {trigger} -> {msg}")
        elif rtype == "cloudflare":
            ok, msg = await run_cloudflare_action(rule["action"])
            await a_log_event("info" if ok else "error", f"Rule: Cloudflare {rule['action']} on {trigger} -> {msg}")
        elif rtype == "nut":
            ok, msg = await run_nut_action(rule["action"])
            await a_log_event("info" if ok else "error", f"Rule: NUT {rule['action']} on {trigger} -> {msg}")
        else:
            ok, msg = container_action(rule["container"], rule["action"])
            await a_log_event(
                "info" if ok else "error",
                f"Rule: {rule['action']} '{rule['container']}' on {trigger} -> {msg}",
            )


async def apply_rules(new_state: str):
    trigger_map = {"failover": "failover", "primary": "restored", "down": "down"}
    trigger = trigger_map.get(new_state)
    if trigger is None:
        await a_log_event("warn", f"WAN state changed to '{new_state}' — no rules apply")
        return
    await fire_trigger(trigger)


async def live_stats_loop():
    log.info("Live stats loop started")
    client: Optional[UniFiClient] = None
    last_settings: Optional[tuple] = None
    ticks = 0
    metrics_every = max(1, METRICS_WRITE_INTERVAL // LIVE_INTERVAL)

    while True:
        try:
            host    = get_setting("unifi_host")
            api_key = get_setting("unifi_api_key")
            site    = get_setting("unifi_site", "default")
            if not (host and api_key):
                await asyncio.sleep(LIVE_INTERVAL)
                continue

            current = (host, api_key, site)
            if client is None or current != last_settings:
                if client:
                    await client.close()
                client = UniFiClient(host, api_key, site)
                last_settings = current

            state.live_gw_info = await client.get_gateway_info()
            ticks += 1
            if ticks % metrics_every == 0:
                await a_write_metric(state.live_gw_info)

            threshold = int(get_setting("latency_threshold_ms", "0"))
            if threshold > 0:
                lat = state.live_gw_info.get("active_wan_latency") or 0
                cooldown_s = int(get_setting("latency_cooldown_min", "5")) * 60
                if lat > threshold and (time.time() - state.latency_last_fired) > cooldown_s:
                    state.latency_last_fired = time.time()
                    await a_log_event("warn", f"High latency: {lat} ms (threshold {threshold} ms)")
                    _create_task(fire_trigger("high_latency"))
                    _create_task(send_notification(
                        "WaniFi high latency",
                        f"Latency {lat} ms exceeds threshold {threshold} ms",
                        priority="default", tags="warning",
                        event="high_latency",
                    ))
        except asyncio.CancelledError:
            if client:
                await client.close()
            raise
        except Exception as e:
            log.warning("Live stats error: %s", e)
            if client:
                await client.close()
            client, last_settings = None, None
        await asyncio.sleep(LIVE_INTERVAL)


async def watcher_loop():
    log.info("Watcher loop started")
    client: Optional[UniFiClient] = None
    last_settings: Optional[tuple] = None
    last_purge_day: Optional[str] = None

    while True:
        try:
            host    = get_setting("unifi_host")
            api_key = get_setting("unifi_api_key")
            site    = get_setting("unifi_site", "default")
            primary  = get_setting("primary_wan", "wan")
            failover = get_setting("failover_wan", "wan2")
            interval = int(get_setting("poll_interval", str(POLL_INTERVAL_DEFAULT)))

            if not (host and api_key):
                state.last_error = "UniFi not configured"
                await asyncio.sleep(10)
                continue

            current = (host, api_key, site)
            if client is None or current != last_settings:
                if client:
                    await client.close()
                client = UniFiClient(host, api_key, site)
                last_settings = current

            wans = await client.get_gateway_health()
            gw_info = await client.get_gateway_info()
            new_state = determine_active_wan(wans, primary, failover, gw_info)
            state.last_check = datetime.now(timezone.utc).isoformat()
            state.last_error = None

            await a_set_state("last_wans",    json.dumps(wans))
            await a_set_state("gateway_info", json.dumps(gw_info))
            await a_set_state("active_wan",   new_state)

            previous = state.current_wan
            if previous != new_state:
                changed_at = datetime.now(timezone.utc).isoformat()
                if previous is not None:
                    await a_log_event("info", f"WAN state change: {previous} -> {new_state}")
                    await apply_rules(new_state)
                    if new_state == "failover":
                        name = get_setting("failover_wan_name") or failover
                        _rx  = state.live_gw_info.get("active_wan_rx_mbps", 0)
                        _tx  = state.live_gw_info.get("active_wan_tx_mbps", 0)
                        _lat = state.live_gw_info.get("active_wan_latency") or "—"
                        _ip  = state.live_gw_info.get("active_wan_ip", "")
                        _metrics = f"\n↓ {_rx} Mbps  ↑ {_tx} Mbps  latency {_lat} ms"
                        if _ip:
                            _metrics += f"  IP {_ip}"
                        _create_task(send_notification(
                            "WAN Failover",
                            f"Primary WAN is down — switched to {name}{_metrics}",
                            priority="high", tags="warning,rotating_light",
                            event="failover",
                        ))
                    elif new_state == "primary":
                        name = get_setting("primary_wan_name") or primary
                        _rx  = state.live_gw_info.get("active_wan_rx_mbps", 0)
                        _tx  = state.live_gw_info.get("active_wan_tx_mbps", 0)
                        _lat = state.live_gw_info.get("active_wan_latency") or "—"
                        _ip  = state.live_gw_info.get("active_wan_ip", "")
                        _metrics = f"\n↓ {_rx} Mbps  ↑ {_tx} Mbps  latency {_lat} ms"
                        if _ip:
                            _metrics += f"  IP {_ip}"
                        _create_task(send_notification(
                            "WAN Restored",
                            f"Primary WAN ({name}) is back online{_metrics}",
                            priority="default", tags="white_check_mark",
                            event="restored",
                        ))
                else:
                    await a_log_event("info", f"Initial WAN state: {new_state}")
                    stored_state      = get_state("active_wan")
                    stored_changed_at = get_state("state_changed_at")
                    if stored_state == new_state and stored_changed_at:
                        changed_at = stored_changed_at
                state.current_wan = new_state
                state.state_changed_at = changed_at
                await a_set_state("state_changed_at", changed_at)

            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if last_purge_day != today:
                retention = int(get_setting("event_retention_days", "30"))
                await asyncio.to_thread(purge_old_events, retention)
                last_purge_day = today

            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            log.info("Watcher loop cancelled")
            if client:
                await client.close()
            raise
        except Exception as e:
            state.last_error = str(e)
            await a_log_event("error", f"Watcher error: {e}")
            _create_task(send_notification(
                "WaniFi Watcher Error", str(e), priority="low", tags="x",
                event="error",
            ))
            if client:
                await client.close()
            client, last_settings = None, None
            await asyncio.sleep(15)
