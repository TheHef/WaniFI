"""UniFi SSH client — collects WAN/gateway data via SSH as an alternative to the API key."""
import asyncio
import json
import time
from typing import Optional
from urllib.parse import urlparse

from .config import log

try:
    import asyncssh
    _HAS_ASYNCSSH = True
except ImportError:
    _HAS_ASYNCSSH = False


class UniFiSSHClient:
    """Async SSH client that mimics the shape of UniFiClient for the watcher loops.

    Supports two data sources:
    1. ``mca-dump`` — available on UDM/UCG/UDR/UDM-Pro.
       On UCG-Max / newer UniFi OS the JSON layout differs from older UDM:
         - ``uplink``      → **string** (Linux interface name, e.g. "eth4")
         - ``if_table``    → list of interface dicts with WAN traffic data
         - ``system-stats``→ dict with cpu/mem as *string* percentages ("25.9")
         - ``uptime_stats``→ dict keyed by WAN name ("WAN", "WAN3") with
                             availability float and latency_average int
       On older UDM / UDM-Pro the layout is:
         - ``uplink``      → dict with ip, rx_bytes-r, tx_bytes-r, latency …
         - ``sys_stats``   → dict with cpu/mem as numbers or fractions
    2. /proc fallback — ``ip route``, ``/proc/net/dev``, ``/proc/loadavg``,
       ``/proc/meminfo``.  Useful for plain OpenWrt or similar devices.
    """

    def __init__(self, host: str, port: int = 22, username: str = "root", password: str = ""):
        # Accept both a bare hostname and a URL like "https://192.168.1.1"
        if "://" in host:
            parsed = urlparse(host)
            self._host = parsed.hostname or host
        else:
            self._host = host
        self._port     = port
        self._username = username
        self._password = password
        self._conn     = None
        self._prev_bytes: dict = {}  # iface -> (rx_bytes, tx_bytes, monotonic_ts)

    # ── Connection ───────────────────────────────────────────────────────────

    async def _ensure_connected(self):
        if not _HAS_ASYNCSSH:
            raise RuntimeError("asyncssh not installed — add asyncssh to requirements.txt")
        if self._conn is None:
            self._conn = await asyncssh.connect(
                self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                known_hosts=None,       # skip host-key verification (self-signed)
                connect_timeout=10,
            )

    async def _run(self, cmd: str) -> str:
        await self._ensure_connected()
        r = await self._conn.run(cmd, check=False, timeout=10)
        return (r.stdout or "").strip()

    async def run_raw(self, cmd: str) -> str:
        """Public wrapper used by the debug endpoint."""
        return await self._run(cmd)

    async def close(self):
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    async def test_connection(self) -> tuple[bool, str]:
        if not _HAS_ASYNCSSH:
            return False, "asyncssh not installed"
        try:
            out = await self._run("hostname; uname -r 2>/dev/null || echo ''")
            return True, f"Connected — {out.splitlines()[0] if out else '(no output)'}"
        except Exception as e:
            return False, str(e)

    # ── Parsers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_proc_net_dev(text: str) -> dict[str, tuple[int, int]]:
        """Return {iface: (rx_bytes, tx_bytes)} from /proc/net/dev text."""
        out: dict[str, tuple[int, int]] = {}
        for line in text.splitlines()[2:]:  # skip 2 header lines
            if ":" not in line:
                continue
            iface, _, rest = line.partition(":")
            nums = rest.split()
            if len(nums) >= 9:
                try:
                    out[iface.strip()] = (int(nums[0]), int(nums[8]))
                except ValueError:
                    pass
        return out

    @staticmethod
    def _parse_default_routes(text: str) -> list[dict]:
        """Parse 'ip route show' output into sorted list of default-route dicts."""
        routes: list[dict] = []
        for line in text.splitlines():
            if not line.startswith("default"):
                continue
            parts = line.split()
            r: dict = {"via": "", "dev": "", "metric": 0}
            for i, p in enumerate(parts):
                if p in ("via", "dev") and i + 1 < len(parts):
                    r[p] = parts[i + 1]
                elif p == "metric" and i + 1 < len(parts):
                    try:
                        r["metric"] = int(parts[i + 1])
                    except ValueError:
                        pass
            if r["dev"]:
                routes.append(r)
        routes.sort(key=lambda x: x["metric"])
        return routes

    @staticmethod
    def _parse_meminfo(text: str) -> Optional[int]:
        """Return memory usage % from /proc/meminfo."""
        vals: dict[str, int] = {}
        for line in text.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                try:
                    vals[k.strip()] = int(v.strip().split()[0])
                except (ValueError, IndexError):
                    pass
        total = vals.get("MemTotal", 0)
        avail = vals.get("MemAvailable") or vals.get("MemFree", 0)
        return round((1 - avail / total) * 100) if total else None

    @staticmethod
    def _parse_loadavg(text: str) -> Optional[float]:
        """Return 1-min load as CPU % from /proc/loadavg."""
        try:
            return round(min(float(text.split()[0]) * 100, 100), 1)
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _parse_mca_dump(text: str, host: str) -> Optional[dict]:
        """Parse mca-dump JSON into a gateway-info dict.

        Handles two different JSON layouts:

        **UCG-Max / newer UniFi OS:**
        - ``uplink``       string  — Linux interface name of the active WAN
        - ``if_table``     list    — per-interface stats including rx_rate/tx_rate
        - ``system-stats`` dict    — {"cpu": "25.9", "mem": "75.5", "uptime": "…"}
        - ``uptime_stats`` dict    — {"WAN": {"availability": 100.0, "latency_average": 13}}
        - ``geo_info``     dict    — {"WAN": {"isp_name": "…"}}

        **Older UDM / UDM-Pro:**
        - ``uplink``       dict    — {ip, rx_bytes-r, tx_bytes-r, latency, comment, …}
        - ``sys_stats``    dict    — {cpu, mem, loadavg_1, mem_total, mem_used, …}
        """
        try:
            data = json.loads(text.replace("\x00", ""))
        except Exception:
            return None

        uplink_raw = data.get("uplink")

        # ── CPU ──────────────────────────────────────────────────────────────
        cpu_val: Optional[float] = None

        # 1. Try UCG-Max "system-stats" (hyphenated key) — string percentages
        sys_stats_h = data.get("system-stats") or {}
        if sys_stats_h.get("cpu") is not None:
            try:
                cpu_val = round(float(sys_stats_h["cpu"]), 1)
            except (TypeError, ValueError):
                pass

        # 2. Fall back to older "sys_stats" dict
        if cpu_val is None:
            sys_stats = data.get("sys_stats") or {}
            cpu_raw = (
                sys_stats.get("cpu") or
                sys_stats.get("loadavg_1") or
                (data.get("cpu") or {}).get("avg_5s")
            )
            if cpu_raw is not None:
                try:
                    cpu_val = float(cpu_raw)
                    if cpu_val <= 1.0:
                        cpu_val = round(cpu_val * 100, 1)
                except (TypeError, ValueError):
                    pass

        # ── Memory ───────────────────────────────────────────────────────────
        mem_val: Optional[int] = None

        # 1. UCG-Max "system-stats" — string percentage like "75.5"
        if sys_stats_h.get("mem") is not None:
            try:
                m = float(sys_stats_h["mem"])
                mem_val = round(m * 100) if m <= 1.0 else round(m)
            except (TypeError, ValueError):
                pass

        # 2. Older "sys_stats" fraction (0.0–1.0) or integer percent
        if mem_val is None:
            sys_stats = data.get("sys_stats") or {}
            raw_mem = sys_stats.get("mem")
            if raw_mem is not None:
                try:
                    m = float(raw_mem)
                    mem_val = round(m * 100) if m <= 1.0 else round(m)
                except (TypeError, ValueError):
                    pass

        # 3. Raw totals from sys_stats or top-level
        if mem_val is None:
            sys_stats = data.get("sys_stats") or {}
            m_total = sys_stats.get("mem_total") or data.get("mem_total")
            m_used  = sys_stats.get("mem_used")  or data.get("mem_used")
            if m_total and m_used:
                try:
                    mem_val = round(int(m_used) / int(m_total) * 100)
                except (TypeError, ValueError, ZeroDivisionError):
                    pass

        # ── WAN / uplink data ─────────────────────────────────────────────────
        active_wan_name  = ""
        active_wan_ip    = ""
        active_wan_type  = ""
        rx_mbps          = 0.0
        tx_mbps          = 0.0
        wan_latency: Optional[int] = None
        wan_uptime: Optional[int]  = None
        wan_xput_down: Optional[float] = None
        wan_xput_up:   Optional[float] = None

        if isinstance(uplink_raw, str):
            # ── UCG-Max layout ────────────────────────────────────────────────
            # uplink is a bare interface name like "eth4"; full data in if_table
            if_table: list[dict] = data.get("if_table") or []

            # Active interface = entry whose "name" matches uplink string
            active_iface = next(
                (i for i in if_table if i.get("name") == uplink_raw), None
            )

            # If not found by name, fall back to first WAN-ish entry
            if active_iface is None:
                for i in if_table:
                    comment = (i.get("comment") or "").upper()
                    if comment.startswith("WAN"):
                        active_iface = i
                        break

            if active_iface:
                active_wan_name = active_iface.get("comment") or uplink_raw.upper()
                active_wan_ip   = active_iface.get("ip", "")
                active_wan_type = (active_iface.get("comment") or "").lower()
                wan_latency     = active_iface.get("latency")
                wan_uptime      = active_iface.get("uptime")
                # rx_rate / tx_rate are bytes/sec
                rx_bps = active_iface.get("rx_rate") or active_iface.get("rx_bytes-r") or 0
                tx_bps = active_iface.get("tx_rate") or active_iface.get("tx_bytes-r") or 0
                rx_mbps = round(rx_bps * 8 / 1_000_000, 2)
                tx_mbps = round(tx_bps * 8 / 1_000_000, 2)

            # uptime_stats may carry richer latency per-WAN
            uptime_stats = data.get("uptime_stats") or {}
            if active_wan_name and active_wan_name in uptime_stats:
                entry = uptime_stats[active_wan_name]
                if wan_latency is None:
                    wan_latency = entry.get("latency_average")

        elif isinstance(uplink_raw, dict):
            # ── Older UDM / UDM-Pro layout ────────────────────────────────────
            uplink = uplink_raw
            active_wan_name = (
                uplink.get("comment") or
                uplink.get("name")    or
                uplink.get("type")    or
                ""
            )
            active_wan_type = uplink.get("type", "")
            active_wan_ip   = uplink.get("ip", "")
            wan_latency     = uplink.get("latency")
            wan_uptime      = uplink.get("uptime")
            wan_xput_down   = uplink.get("xput_down")
            wan_xput_up     = uplink.get("xput_up")

            rx = uplink.get("rx_bytes-r") or uplink.get("rxbytes-r") or 0
            tx = uplink.get("tx_bytes-r") or uplink.get("txbytes-r") or 0
            rx_mbps = round(rx * 8 / 1_000_000, 2)
            tx_mbps = round(tx * 8 / 1_000_000, 2)

        return {
            "active_wan":           active_wan_name,
            "active_wan_type":      active_wan_type,
            "active_wan_ip":        active_wan_ip,
            "active_wan_rx_mbps":   rx_mbps,
            "active_wan_tx_mbps":   tx_mbps,
            "active_wan_latency":   wan_latency,
            "active_wan_uptime":    wan_uptime,
            "active_wan_xput_down": wan_xput_down,
            "active_wan_xput_up":   wan_xput_up,
            "gw_name":  data.get("hostname") or data.get("name", ""),
            "gw_model": data.get("model", ""),
            "gw_ip":    host,
            "gw_cpu":   cpu_val,
            "gw_mem":   mem_val,
            "extra_devices": [],
        }

    # ── Public API (shape-compatible with UniFiClient) ───────────────────────

    async def discover_wans(self) -> list[dict]:
        """Return WAN interface list in the same format as the /api/test-unifi endpoint.

        Each entry:
          subsystem    – lowercase WAN name used in settings ("wan", "wan3", …)
          status       – "ok" or "down"
          wan_ip       – current WAN IP
          isp_name     – ISP name from geo_info if available
          active       – True for the currently active uplink
          device_model – gateway model (reported by mca-dump)
          device_name  – gateway hostname
        """
        try:
            mca_text = await self._run("mca-dump 2>/dev/null")
            if not (mca_text and "{" in mca_text):
                return []
            data = json.loads(mca_text.replace("\x00", ""))
        except Exception:
            return []

        uplink_raw   = data.get("uplink", "")
        if_table:    list[dict] = data.get("if_table") or []
        geo_info:    dict = data.get("geo_info")    or {}
        uptime_stats: dict = data.get("uptime_stats") or {}
        gw_model = data.get("model", "")
        gw_name  = data.get("hostname") or data.get("name", "")

        if if_table:
            # UCG-Max layout: find all WAN interfaces in if_table
            wan_ifaces = [
                i for i in if_table
                if (i.get("comment") or "").upper().startswith("WAN")
            ]
            result: list[dict] = []
            for iface in wan_ifaces:
                comment    = iface.get("comment", "")       # "WAN", "WAN3", …
                name_lower = comment.lower()                 # "wan", "wan3", …

                # Active = the interface whose Linux name matches the uplink string
                is_active = isinstance(uplink_raw, str) and iface.get("name") == uplink_raw

                # Status from uptime_stats if available, else from if_table "up" flag
                status = "down"
                if comment in uptime_stats:
                    avail  = uptime_stats[comment].get("availability", 0)
                    status = "ok" if avail and avail >= 100.0 else "down"
                elif iface.get("up"):
                    status = "ok"

                # ISP from geo_info
                isp_name: Optional[str] = None
                if comment in geo_info:
                    isp_name = geo_info[comment].get("isp_name")

                result.append({
                    "subsystem":    name_lower,
                    "status":       status,
                    "wan_ip":       iface.get("ip", ""),
                    "isp_name":     isp_name,
                    "active":       is_active,
                    "device_model": gw_model,
                    "device_name":  gw_name,
                })
            return result

        # Older UDM layout (uplink is a dict) — build minimal list from uplink data
        if isinstance(uplink_raw, dict):
            active_name = (
                uplink_raw.get("comment") or
                uplink_raw.get("name")    or
                uplink_raw.get("type")    or "wan"
            ).lower()
            wan_ip = uplink_raw.get("ip", "")
            return [{
                "subsystem":    active_name,
                "status":       "ok" if wan_ip else "down",
                "wan_ip":       wan_ip,
                "isp_name":     None,
                "active":       True,
                "device_model": gw_model,
                "device_name":  gw_name,
            }]

        return []

    async def get_gateway_health(self, primary: str = "wan", failover: str = "wan2") -> list[dict]:
        """Return a minimal WAN health list that ``determine_active_wan()`` can consume.

        Strategy 1: use ``uptime_stats`` from mca-dump — this dict is keyed by the
        human WAN name ("WAN", "WAN3", …) and has an ``availability`` float (100 = up).
        This works on UCG-Max where WAN traffic lives in a separate Linux routing
        namespace, so ``ip route`` in the main shell shows no default routes at all.

        Strategy 2: fall back to ``ip route show table all`` for non-UCG devices
        (plain OpenWrt etc.).
        """
        # ── Strategy 1: mca-dump with uptime_stats ───────────────────────────
        try:
            mca_text = await self._run("mca-dump 2>/dev/null")
            if mca_text and "{" in mca_text:
                data = json.loads(mca_text.replace("\x00", ""))

                uptime_stats: dict = data.get("uptime_stats") or {}
                if_table: list[dict] = data.get("if_table") or []
                uplink_raw = data.get("uplink")

                if uptime_stats:
                    # Build health list directly from uptime_stats keys.
                    # Keys are the human WAN names used in settings ("WAN", "WAN3", …)
                    # availability=100.0 → up, anything lower or missing → down.
                    health: list[dict] = []
                    for wan_key in (primary, failover):
                        # Match case-insensitively — settings may store "wan" / "wan2"
                        # while uptime_stats has "WAN" / "WAN3" etc.
                        matched_key = next(
                            (k for k in uptime_stats if k.lower() == wan_key.lower()),
                            None,
                        )
                        if matched_key:
                            entry  = uptime_stats[matched_key]
                            avail  = entry.get("availability", 0)
                            status = "ok" if avail and avail >= 100.0 else "down"
                            # Resolve IP from if_table using the WAN comment
                            wan_ip = ""
                            for iface in if_table:
                                if (iface.get("comment") or "").lower() == matched_key.lower():
                                    wan_ip = iface.get("ip", "")
                                    break
                            health.append({"subsystem": wan_key, "status": status, "wan_ip": wan_ip})
                        else:
                            health.append({"subsystem": wan_key, "status": "down", "wan_ip": ""})
                    return health

                # No uptime_stats — fall back to uplink string / ip field
                if isinstance(uplink_raw, str) and if_table:
                    active_iface = next(
                        (i for i in if_table if i.get("name") == uplink_raw), None
                    )
                    if active_iface:
                        active_comment = (active_iface.get("comment") or "").lower()
                        wan_ip = active_iface.get("ip", "")
                        if active_comment == failover.lower():
                            return [
                                {"subsystem": primary,  "status": "down", "wan_ip": ""},
                                {"subsystem": failover, "status": "ok",   "wan_ip": wan_ip},
                            ]
                        else:
                            return [
                                {"subsystem": primary,  "status": "ok",   "wan_ip": wan_ip},
                                {"subsystem": failover, "status": "down", "wan_ip": ""},
                            ]

                elif isinstance(uplink_raw, dict):
                    # Older UDM layout
                    wan_ip = uplink_raw.get("ip", "")
                    if wan_ip:
                        active_id = (
                            uplink_raw.get("comment") or
                            uplink_raw.get("name")    or
                            uplink_raw.get("type")    or ""
                        ).lower()
                        if active_id == failover.lower():
                            return [
                                {"subsystem": primary,  "status": "down", "wan_ip": ""},
                                {"subsystem": failover, "status": "ok",   "wan_ip": wan_ip},
                            ]
                        return [
                            {"subsystem": primary,  "status": "ok",   "wan_ip": wan_ip},
                            {"subsystem": failover, "status": "down", "wan_ip": ""},
                        ]
                    else:
                        return [
                            {"subsystem": primary,  "status": "down", "wan_ip": ""},
                            {"subsystem": failover, "status": "down", "wan_ip": ""},
                        ]
        except Exception:
            pass

        # ── Strategy 2: ip route fallback (non-UCG/UDM devices) ─────────────
        try:
            # On UCG/UDM main-ns ip route shows nothing useful; try table all first
            routes_text = await self._run(
                "ip route show table all 2>/dev/null | grep '^default' | head -10"
            )
            if not routes_text:
                routes_text = await self._run("ip route show 2>/dev/null")
        except Exception:
            return []

        routes = self._parse_default_routes(routes_text)
        if not routes:
            return [
                {"subsystem": primary,  "status": "down", "wan_ip": ""},
                {"subsystem": failover, "status": "down", "wan_ip": ""},
            ]
        if len(routes) == 1:
            return [
                {"subsystem": primary,  "status": "ok",   "wan_ip": routes[0]["via"]},
                {"subsystem": failover, "status": "down", "wan_ip": ""},
            ]
        return [
            {"subsystem": primary,  "status": "ok", "wan_ip": routes[0]["via"]},
            {"subsystem": failover, "status": "ok", "wan_ip": routes[1]["via"]},
        ]

    async def get_gateway_info(self) -> dict:
        """Return live gateway stats compatible with ``UniFiClient.get_gateway_info()``."""

        # ── Try mca-dump first (UDM / UCG / UDR / UDM-Pro) ──────────────────
        try:
            mca_text = await self._run("mca-dump 2>/dev/null")
            if mca_text and "{" in mca_text:
                parsed = self._parse_mca_dump(mca_text, self._host)
                if parsed:
                    return parsed
        except Exception:
            pass

        # ── /proc fallback ────────────────────────────────────────────────────
        info: dict = {"gw_ip": self._host, "extra_devices": [], "gw_model": ""}
        try:
            results = await asyncio.gather(
                self._run("ip route show 2>/dev/null"),
                self._run("cat /proc/net/dev 2>/dev/null"),
                self._run("cat /proc/loadavg 2>/dev/null"),
                self._run("cat /proc/meminfo 2>/dev/null"),
                self._run("hostname 2>/dev/null"),
                return_exceptions=True,
            )
            routes_text, net_dev_text, loadavg_text, meminfo_text, hostname = [
                v if isinstance(v, str) else "" for v in results
            ]

            routes       = self._parse_default_routes(routes_text)
            active_iface = routes[0]["dev"] if routes else ""
            active_ip    = routes[0]["via"] if routes else ""

            rx_mbps, tx_mbps = 0.0, 0.0
            if net_dev_text and active_iface:
                dev_stats = self._parse_proc_net_dev(net_dev_text)
                if active_iface in dev_stats:
                    rx_now, tx_now = dev_stats[active_iface]
                    now = time.monotonic()
                    if active_iface in self._prev_bytes:
                        p_rx, p_tx, p_t = self._prev_bytes[active_iface]
                        dt = now - p_t
                        if dt > 0 and rx_now >= p_rx:
                            rx_mbps = round((rx_now - p_rx) * 8 / dt / 1_000_000, 2)
                            tx_mbps = round((tx_now - p_tx) * 8 / dt / 1_000_000, 2)
                    self._prev_bytes[active_iface] = (rx_now, tx_now, now)

            info.update({
                "active_wan":         active_iface.upper() if active_iface else "",
                "active_wan_ip":      active_ip,
                "active_wan_rx_mbps": rx_mbps,
                "active_wan_tx_mbps": tx_mbps,
                "gw_name": hostname.splitlines()[0] if hostname else "",
                "gw_cpu":  self._parse_loadavg(loadavg_text) if loadavg_text else None,
                "gw_mem":  self._parse_meminfo(meminfo_text)  if meminfo_text else None,
            })
        except Exception as e:
            log.warning("UniFi SSH get_gateway_info error: %s", e)

        return info
