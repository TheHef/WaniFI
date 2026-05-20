"""OpenWrt LuCI RPC client."""
import asyncio
import time
from typing import Optional
from urllib.parse import urlparse

import httpx

from .config import log

# Interfaces to ignore when discovering WAN candidates
_IGNORE = {"loopback", "lan", "lan6", "guest", "guest6", "docker", "br-lan"}

# Null session used for ubus native login
_NULL_SESSION = "00000000000000000000000000000000"


class OpenWrtClient:
    def __init__(self, url: str, password: str, username: str = "root"):
        self._base = url.rstrip("/")
        self._username = username
        self._password = password
        self._token: Optional[str] = None
        self._mode: Optional[str] = None   # "ubus" | "luci"
        self._http = httpx.AsyncClient(verify=False, timeout=10)

    async def close(self):
        await self._http.aclose()

    async def _auth_ubus(self) -> bool:
        """Auth via native rpcd (/ubus session login)."""
        try:
            r = await self._http.post(
                f"{self._base}/ubus",
                json={
                    "jsonrpc": "2.0", "id": 1, "method": "call",
                    "params": [_NULL_SESSION, "session", "login", {
                        "username": self._username, "password": self._password,
                    }],
                },
            )
            result = r.json().get("result")
            if isinstance(result, list) and result[0] == 0:
                session = result[1].get("ubus_rpc_session", "")
                if session and session.replace("0", ""):
                    self._token = session
                    self._mode = "ubus"
                    return True
        except Exception as e:
            log.debug("OpenWrt ubus-native auth failed: %s", e)
        return False

    async def _auth_luci(self) -> bool:
        """Auth via LuCI RPC (/cgi-bin/luci/rpc/auth)."""
        try:
            r = await self._http.post(
                f"{self._base}/cgi-bin/luci/rpc/auth",
                json={"id": 1, "method": "login", "params": [self._username, self._password]},
            )
            token = r.json().get("result", "")
            if token and token.replace("0", ""):
                self._token = token
                self._mode = "luci"
                return True
        except Exception as e:
            log.debug("OpenWrt luci-rpc auth failed: %s", e)
        return False

    async def _auth(self) -> bool:
        # Try native ubus first (GL-iNet, stock OpenWrt), then LuCI RPC fallback
        if await self._auth_ubus():
            return True
        return await self._auth_luci()

    async def _ubus(self, service: str, method: str, params: dict | None = None) -> Optional[dict]:
        """Make a ubus call, re-authing once on permission denied."""
        for attempt in range(2):
            if not self._token and not await self._auth():
                return None
            try:
                if self._mode == "ubus":
                    r = await self._http.post(
                        f"{self._base}/ubus",
                        json={
                            "jsonrpc": "2.0", "id": 1, "method": "call",
                            "params": [self._token, service, method, params or {}],
                        },
                    )
                else:
                    r = await self._http.post(
                        f"{self._base}/cgi-bin/luci/rpc/ubus",
                        json={
                            "jsonrpc": "2.0", "id": 1, "method": "call",
                            "params": [self._token, service, method, params or {}],
                        },
                        cookies={"sysauth": self._token, "sysauth_https": self._token},
                    )
                result = r.json().get("result")
                if isinstance(result, list) and result[0] == 0:
                    return result[1]
                if isinstance(result, list) and result[0] in (6, 7):
                    # permission denied / no data — re-auth
                    self._token = None
                    self._mode = None
                    continue
                return None
            except Exception as e:
                log.warning("OpenWrt ubus error (attempt %d): %s", attempt + 1, e)
                return None
        return None

    async def get_interfaces(self) -> list[dict]:
        """Return all network interfaces from OpenWrt."""
        data = await self._ubus("network.interface", "dump")
        return (data or {}).get("interface", [])

    async def get_system_info(self) -> dict:
        """Return system memory and load from OpenWrt."""
        return await self._ubus("system", "info") or {}

    async def get_wan_interfaces(self) -> list[dict]:
        """Return WAN-candidate interfaces (excludes LAN, loopback, IPv6 aliases)."""
        ifaces = await self.get_interfaces()
        return [
            i for i in ifaces
            if i.get("interface", "").lower() not in _IGNORE
            and not i.get("interface", "").endswith("6")
        ]

    async def test_connection(self) -> tuple[bool, str]:
        if not await self._auth():
            return False, "Authentication failed — check URL and password"
        ifaces = await self.get_interfaces()
        if not ifaces:
            return False, "Authenticated but no interfaces returned"
        wan_ifaces = await self.get_wan_interfaces()
        names = ", ".join(i["interface"] for i in wan_ifaces) or "none detected"
        return True, f"Connected ({self._mode}) — WAN candidates: {names}"


async def ping_latency(host: str = "1.1.1.1") -> Optional[float]:
    """TCP connect latency to host:53 in ms — no ICMP/root/NET_RAW needed."""
    try:
        t0 = time.monotonic()
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, 53),
            timeout=5.0,
        )
        ms = round((time.monotonic() - t0) * 1000, 1)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return ms
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Pure functions — no I/O
# ---------------------------------------------------------------------------

def determine_active_wan_openwrt(
    interfaces: list[dict],
    primary_iface: str,
    failover_iface: str,
) -> str:
    """Resolve active WAN from an OpenWrt interface dump."""
    imap = {i["interface"]: i for i in interfaces}
    p = imap.get(primary_iface, {})
    f = imap.get(failover_iface, {})
    p_up = p.get("up", False) and bool(p.get("ipv4-address"))
    f_up = f.get("up", False) and bool(f.get("ipv4-address"))
    if p_up:
        return "primary"
    if f_up:
        return "failover"
    return "down"


def build_live_info_openwrt(
    interfaces: list[dict],
    primary_iface: str,
    failover_iface: str,
    wan_state: str,
) -> dict:
    """Build a live_gw_info dict from OpenWrt interface data."""
    imap = {i["interface"]: i for i in interfaces}
    if wan_state == "primary":
        active, active_name = imap.get(primary_iface, {}), primary_iface
    elif wan_state == "failover":
        active, active_name = imap.get(failover_iface, {}), failover_iface
    else:
        active, active_name = {}, ""

    ipv4 = active.get("ipv4-address", [])
    ip = ipv4[0]["address"] if ipv4 else ""

    return {
        "active_wan":         active_name,
        "active_wan_ip":      ip,
        "active_wan_uptime":  active.get("uptime", 0),
        "active_wan_rx_mbps": 0.0,
        "active_wan_tx_mbps": 0.0,
        "active_wan_latency": None,
        "gw_cpu":             None,
        "gw_mem":             None,
        "gw_model":           "OPENWRT",
        "router_type":        "openwrt",
    }
