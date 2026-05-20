"""OpenWrt LuCI RPC client — completely independent from the UniFi client."""
from typing import Optional

import httpx

from .config import log

# Interfaces to ignore when discovering WAN candidates
_IGNORE = {"loopback", "lan", "lan6", "guest", "guest6", "docker", "br-lan"}


class OpenWrtClient:
    def __init__(self, url: str, password: str, username: str = "root"):
        self._base = url.rstrip("/")
        self._username = username
        self._password = password
        self._token: Optional[str] = None
        self._http = httpx.AsyncClient(verify=False, timeout=10)

    async def close(self):
        await self._http.aclose()

    async def _auth(self) -> bool:
        try:
            r = await self._http.post(
                f"{self._base}/cgi-bin/luci/rpc/auth",
                json={"id": 1, "method": "login", "params": [self._username, self._password]},
            )
            token = r.json().get("result", "")
            if token and token.replace("0", ""):   # all-zeros = auth failed
                self._token = token
                return True
            self._token = None
            return False
        except Exception as e:
            log.warning("OpenWrt auth error: %s", e)
            return False

    async def _ubus(self, service: str, method: str, params: dict | None = None) -> Optional[dict]:
        """Make a ubus call via LuCI RPC, re-authing once on permission denied."""
        for attempt in range(2):
            if not self._token and not await self._auth():
                return None
            try:
                r = await self._http.post(
                    f"{self._base}/cgi-bin/luci/rpc/ubus",
                    json={
                        "jsonrpc": "2.0", "id": 1, "method": "call",
                        "params": [self._token, service, method, params or {}],
                    },
                )
                result = r.json().get("result")
                if isinstance(result, list) and result[0] == 0:
                    return result[1]
                if isinstance(result, list) and result[0] in (6, 7):
                    # UBUS_STATUS_PERMISSION_DENIED / NO_DATA — re-auth
                    self._token = None
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
        return True, f"Connected — WAN candidates: {names}"


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
        "router_type":        "openwrt",
    }
