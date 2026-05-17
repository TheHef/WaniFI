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
    get_setting,
    get_state,
    purge_old_events,
)
from .notify import send_notification
from .unifi import UniFiClient


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


async def _qb_action(action: str, value: str = "") -> tuple[bool, str]:
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


async def _emby_action(action: str, value: str = "") -> tuple[bool, str]:
    from .emby import EmbyClient
    url   = get_setting("emby_url", "")
    token = get_setting("emby_token", "")
    if not (url and token):
        return False, "Emby not configured"
    client = EmbyClient(url, token)
    try:
        if action == "set_bitrate_limit":
            return await client.set_bitrate_limit(int(value) if value else 0)
        if action == "clear_bitrate_limit":
            return await client.clear_bitrate_limit()
        if action == "stop_all_sessions":
            return await client.stop_all_sessions()
        return False, f"Unknown Emby action: {action}"
    finally:
        await client.close()


async def fire_trigger(trigger: str):
    from .db import db
    from .docker_ops import container_action

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
            "docker":       "integration_docker",
            "host_command": "integration_host_command",
            "qbittorrent":  "integration_qb",
            "emby":         "integration_emby",
        }.get(rtype)
        if integration_key and get_setting(integration_key, "1") != "1":
            await a_log_event("info", f"Rule '{rule['name']}' skipped (integration disabled)")
            continue

        if rtype == "host_command":
            ok, msg = await execute_host_command(rule["command"])
            await a_log_event(
                "info" if ok else "error",
                f"Rule: host `{rule['command']}` on {trigger} -> {msg}",
            )
        elif rtype == "qbittorrent":
            ok, msg = await _qb_action(rule["action"], rule["container"])
            await a_log_event(
                "info" if ok else "error",
                f"Rule: qB {rule['action']} on {trigger} -> {msg}",
            )
        elif rtype == "emby":
            ok, msg = await _emby_action(rule["action"], rule["container"])
            await a_log_event(
                "info" if ok else "error",
                f"Rule: Emby {rule['action']} on {trigger} -> {msg}",
            )
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
                    asyncio.create_task(fire_trigger("high_latency"))
                    if get_setting("ntfy_on_high_latency", "0") == "1":
                        asyncio.create_task(send_notification(
                            "WaniFi high latency",
                            f"Latency {lat} ms exceeds threshold {threshold} ms",
                            priority="default", tags="warning",
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
                    if new_state == "failover" and get_setting("ntfy_on_failover", "1") == "1":
                        name = get_setting("failover_wan_name") or failover
                        asyncio.create_task(send_notification(
                            "WAN Failover",
                            f"Primary WAN is down — switched to {name}",
                            priority="high", tags="warning,rotating_light",
                        ))
                    elif new_state == "primary" and get_setting("ntfy_on_restored", "1") == "1":
                        name = get_setting("primary_wan_name") or primary
                        asyncio.create_task(send_notification(
                            "WAN Restored",
                            f"Primary WAN ({name}) is back online",
                            priority="default", tags="white_check_mark",
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
            if get_setting("ntfy_on_error", "0") == "1":
                asyncio.create_task(send_notification(
                    "WaniFi Watcher Error", str(e), priority="low", tags="x",
                ))
            if client:
                await client.close()
            client, last_settings = None, None
            await asyncio.sleep(15)
