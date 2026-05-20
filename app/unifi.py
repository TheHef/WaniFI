"""Minimal client for the UniFi Network controller (UDM/UCG/UX)."""
from typing import Optional

import httpx

from .config import UNIFI_HTTP_TIMEOUT, log

GW_TYPES = {"ugw", "udm", "ucg", "usg", "udmpro", "udmse", "ux"}
NON_WAN_TYPES = {"usw", "uap", "uph", "uck", "ubb"}


class UniFiClient:
    """Async client for the UniFi Network controller (UniFi OS 3.x+ API key auth)."""

    def __init__(self, host: str, api_key: str, site: str = "default", verify: bool = False):
        self.host = host.rstrip("/")
        self.site = site
        self.client = httpx.AsyncClient(
            base_url=self.host,
            verify=verify,
            timeout=UNIFI_HTTP_TIMEOUT,
            follow_redirects=False,
            headers={"X-API-KEY": api_key, "Accept": "application/json"},
        )

    async def _get(self, path: str) -> dict:
        resp = await self.client.get(path)
        resp.raise_for_status()
        return resp.json()

    async def get_sites(self) -> list[dict]:
        data = await self._get("/proxy/network/api/self/sites")
        return [
            {"id": s.get("name", ""), "label": s.get("desc") or s.get("name", "")}
            for s in data.get("data", [])
        ]

    async def get_gateway_health(self) -> list[dict]:
        path = f"/proxy/network/api/s/{self.site}/stat/health"
        data = await self._get(path)
        return [i for i in data.get("data", []) if i.get("subsystem", "").startswith("wan")]

    async def get_gateway_info(self) -> dict:
        try:
            path = f"/proxy/network/api/s/{self.site}/stat/device"
            data = await self._get(path)
            items = data.get("data", [])
            gw = next((d for d in items if d.get("type", "").lower() in GW_TYPES), None)
            if not gw:
                return {}

            extra_devices = _collect_extra_devices(items)
            uplink = gw.get("uplink", {})
            gw_cpu, gw_mem = _cpu_mem(gw)
            gw_ip = _management_ip(gw)

            return {
                "active_wan": uplink.get("comment", ""),
                "active_wan_type": uplink.get("type", ""),
                "active_wan_ip": uplink.get("ip", ""),
                "active_wan_rx_mbps": round(uplink.get("rx_bytes-r", 0) * 8 / 1_000_000, 2),
                "active_wan_tx_mbps": round(uplink.get("tx_bytes-r", 0) * 8 / 1_000_000, 2),
                "active_wan_rx_bytes": uplink.get("rx_bytes", 0),
                "active_wan_tx_bytes": uplink.get("tx_bytes", 0),
                "active_wan_latency": uplink.get("latency"),
                "active_wan_uptime":  uplink.get("uptime"),
                "active_wan_xput_down": uplink.get("xput_down"),
                "active_wan_xput_up":   uplink.get("xput_up"),
                "gw_name":  gw.get("name", ""),
                "gw_model": gw.get("model", ""),
                "gw_ip":    gw_ip,
                "gw_cpu":   gw_cpu,
                "gw_mem":   gw_mem,
                "extra_devices": extra_devices,
            }
        except Exception as e:
            log.warning("Gateway info fetch failed: %s", e)
            return {}

    # ── Rule actions ────────────────────────────────────────────────────────

    async def kick_all_clients(self) -> tuple[bool, str]:
        """Disconnect every associated wireless client (forces re-auth/DHCP)."""
        try:
            r = await self.client.get(f"/proxy/network/api/s/{self.site}/stat/sta")
            r.raise_for_status()
            clients = r.json().get("data", [])
            if not clients:
                return True, "No wireless clients connected"
            kicked = 0
            for c in clients:
                mac = c.get("mac", "")
                if not mac:
                    continue
                await self.client.post(
                    f"/proxy/network/api/s/{self.site}/cmd/stamgr",
                    json={"cmd": "kick-sta", "mac": mac},
                )
                kicked += 1
            return True, f"Kicked {kicked} client{'s' if kicked != 1 else ''}"
        except Exception as e:
            return False, str(e)

    async def set_wlan_enabled(self, name: str, enabled: bool) -> tuple[bool, str]:
        """Enable or disable a WLAN by SSID name."""
        try:
            r = await self.client.get(f"/proxy/network/api/s/{self.site}/rest/wlanconf")
            r.raise_for_status()
            wlans = r.json().get("data", [])
            target = next((w for w in wlans if w.get("name", "") == name), None)
            if not target:
                return False, f"WLAN '{name}' not found"
            wid = target.get("_id", "")
            target["enabled"] = enabled
            w = await self.client.put(
                f"/proxy/network/api/s/{self.site}/rest/wlanconf/{wid}",
                json=target,
            )
            if w.status_code < 400:
                state = "enabled" if enabled else "disabled"
                return True, f"WLAN '{name}' {state}"
            return False, f"HTTP {w.status_code}"
        except Exception as e:
            return False, str(e)

    async def set_client_blocked(self, mac: str, block: bool) -> tuple[bool, str]:
        """Block or unblock a client MAC address."""
        cmd = "block-sta" if block else "unblock-sta"
        try:
            r = await self.client.post(
                f"/proxy/network/api/s/{self.site}/cmd/stamgr",
                json={"cmd": cmd, "mac": mac.lower()},
            )
            if r.status_code < 400:
                state = "blocked" if block else "unblocked"
                return True, f"Client {mac} {state}"
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    async def close(self):
        await self.client.aclose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _cpu_mem(dev: dict) -> tuple[Optional[float], Optional[float]]:
    sys_stats = dev.get("sys_stats", {})
    legacy = dev.get("system-stats", {})
    cpu, mem = None, None

    cpu_val = sys_stats.get("cpu_usage")
    if cpu_val is None:
        cpu_val = legacy.get("cpu")
    if cpu_val is not None:
        try:
            cpu = min(round(float(cpu_val), 1), 100.0)
        except (TypeError, ValueError):
            pass

    mem_used  = sys_stats.get("mem_used")
    mem_total = sys_stats.get("mem_total")
    if mem_used is not None and mem_total:
        mem = round(mem_used / mem_total * 100, 1)
    else:
        mem_val = legacy.get("mem")
        if mem_val is not None:
            try:
                mem = round(float(mem_val), 1)
            except (TypeError, ValueError):
                pass
    return cpu, mem


def _management_ip(gw: dict) -> str:
    """Prefer a private LAN IP — gw.ip can be the WAN address on some models."""
    gw_ip = gw.get("ip", "")
    for port in gw.get("port_table", []):
        pip = port.get("ip", "")
        if pip and not port.get("wan_ip") and not port.get("is_uplink"):
            if pip.startswith(("10.", "192.168.", "172.")):
                return pip
    return gw_ip


def _collect_extra_devices(items: list[dict]) -> list[dict]:
    out = []
    for d in items:
        dtype = d.get("type", "").lower()
        if dtype in GW_TYPES or dtype in NON_WAN_TYPES:
            continue
        wan_ip = ""
        isp_name = ""
        signal = _cellular_signal(d)
        for port in d.get("port_table", []):
            if port.get("wan_ip"):
                wan_ip = port["wan_ip"]
                isp_name = port.get("isp_name") or port.get("name_isp") or ""
                break
            if port.get("is_uplink") and port.get("ip"):
                wan_ip = port["ip"]
                break
        cpu, mem = _cpu_mem(d)
        out.append({
            "name":     d.get("name", ""),
            "model":    d.get("model", ""),
            "type":     dtype,
            "ip":       d.get("ip", ""),
            "wan_ip":   wan_ip,
            "isp_name": isp_name,
            "cpu":      cpu,
            "mem":      mem,
            **signal,
        })
    return out


SIGNAL_FIELDS = (
    "signal", "rssi", "rsrp", "rsrq", "sinr",
    "lte_rssi", "lte_rsrp", "lte_rsrq", "lte_sinr",
    "cell_signal", "cellular_signal", "wan_signal", "radio_signal",
    "network_type", "radio", "operator", "carrier",
    "connection_type", "cell_id", "lte_band", "band",
)

NESTED_KEYS = (
    "lte_stats", "cellular", "cellular_stats", "modem_status",
    "radio_status", "wan", "cell", "lte", "wwan", "modem",
)


def _cellular_signal(dev: dict) -> dict:
    """Collect signal metrics from a cellular device (U5G-Max, U-LTE, etc.).

    Looks at the top level, port_table entries, and known nested objects
    since field placement varies between firmware versions and models.
    """
    out: dict = {}

    def grab(src):
        if not isinstance(src, dict):
            return
        for f in SIGNAL_FIELDS:
            if f in out:
                continue
            v = src.get(f)
            if v not in (None, "", 0):
                out[f] = v

    grab(dev)
    for port in dev.get("port_table", []) or []:
        grab(port)
    for key in NESTED_KEYS:
        nested = dev.get(key)
        if isinstance(nested, dict):
            grab(nested)
        elif isinstance(nested, list):
            for item in nested:
                grab(item)

    # Normalise: the dashboard reads xdev.signal or xdev.rsrp first.
    # If we only found a "signal" object instead of a number, ignore it.
    for k in ("signal", "rsrp", "rssi"):
        if isinstance(out.get(k), (dict, list)):
            del out[k]

    return out
