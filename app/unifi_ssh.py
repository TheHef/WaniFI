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
    1. ``mca-dump`` — available on UDM/UCG/UDR/UDM-Pro, returns rich JSON with uplink info.
    2. /proc fallback — ``ip route``, ``/proc/net/dev``, ``/proc/loadavg``, ``/proc/meminfo``.
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
        """Parse mca-dump JSON into a gateway-info dict.  Returns None on parse failure."""
        try:
            data = json.loads(text.replace("\x00", ""))
        except Exception:
            return None

        uplink    = data.get("uplink") or {}
        sys_stats = data.get("sys_stats") or {}

        # WAN identifier — try every field that might carry the logical WAN name.
        # On older UDM/UCG: uplink.comment = "WAN" or uplink.name = "WAN"
        # On UCG-Max / newer OS: uplink.type = "wan" / "wan2" / "wan3"
        # uplink.ifname is the Linux device name (eth8 etc.) — less useful for matching
        wan_name = (
            uplink.get("comment") or
            uplink.get("name")    or
            uplink.get("type")    or   # "wan", "wan2", "wan3" — matches setting values
            ""
        )

        # mca-dump reports per-second byte rates in rx_bytes-r / tx_bytes-r
        rx = uplink.get("rx_bytes-r") or uplink.get("rxbytes-r") or 0
        tx = uplink.get("tx_bytes-r") or uplink.get("txbytes-r") or 0

        # CPU — normalise both 0-100 integers and 0.0-1.0 floats
        cpu_raw = (
            sys_stats.get("cpu") or
            sys_stats.get("loadavg_1") or          # some UCG-Max versions
            (data.get("cpu") or {}).get("avg_5s") or
            None
        )
        cpu_val: Optional[float] = None
        if cpu_raw is not None:
            try:
                cpu_val = float(cpu_raw)
                if cpu_val <= 1.0:               # 0-1 fraction → percent
                    cpu_val = round(cpu_val * 100, 1)
            except (TypeError, ValueError):
                pass

        # Memory — normalise to integer percent
        mem_val: Optional[int] = None
        raw_mem = sys_stats.get("mem")
        if raw_mem is not None:
            try:
                m = float(raw_mem)
                mem_val = round(m * 100) if m <= 1.0 else round(m)
            except (TypeError, ValueError):
                pass
        if mem_val is None:
            # Some devices report raw totals
            m_total = sys_stats.get("mem_total") or data.get("mem_total")
            m_used  = sys_stats.get("mem_used")  or data.get("mem_used")
            if m_total and m_used:
                try:
                    mem_val = round(int(m_used) / int(m_total) * 100)
                except (TypeError, ValueError, ZeroDivisionError):
                    pass

        return {
            "active_wan":           wan_name,
            "active_wan_type":      uplink.get("type", ""),
            "active_wan_ip":        uplink.get("ip", ""),
            "active_wan_rx_mbps":   round(rx * 8 / 1_000_000, 2),
            "active_wan_tx_mbps":   round(tx * 8 / 1_000_000, 2),
            "active_wan_latency":   uplink.get("latency"),
            "active_wan_uptime":    uplink.get("uptime"),
            "active_wan_xput_down": uplink.get("xput_down"),
            "active_wan_xput_up":   uplink.get("xput_up"),
            "gw_name":  data.get("name") or data.get("hostname", ""),
            "gw_model": data.get("model", ""),
            "gw_ip":    host,
            "gw_cpu":   cpu_val,
            "gw_mem":   mem_val,
            "extra_devices": [],
        }

    # ── Public API (shape-compatible with UniFiClient) ───────────────────────

    async def get_gateway_health(self, primary: str = "wan", failover: str = "wan2") -> list[dict]:
        """Return a minimal WAN health list that ``determine_active_wan()`` can consume.

        On UCG/UDM devices the WAN traffic lives in a separate network namespace so
        ``ip route`` in the main shell won't show WAN default routes.  We therefore
        prefer ``mca-dump`` which always reflects the real WAN state, and fall back to
        ``ip route`` only when mca-dump is unavailable (e.g. plain OpenWrt via SSH).
        """
        # ── Strategy 1: mca-dump ─────────────────────────────────────────────
        try:
            mca_text = await self._run("mca-dump 2>/dev/null")
            if mca_text and "{" in mca_text:
                data   = json.loads(mca_text.replace("\x00", ""))
                uplink = data.get("uplink") or {}
                wan_ip = uplink.get("ip", "")

                if wan_ip:
                    # We have an active uplink — work out which WAN it is.
                    # mca-dump reports the active WAN name in comment / name / type.
                    active_id = (
                        uplink.get("comment") or
                        uplink.get("name")    or
                        uplink.get("type")    or
                        ""
                    ).lower()

                    if active_id == failover.lower():
                        # Primary is down, failover is active
                        return [
                            {"subsystem": primary,  "status": "down", "wan_ip": ""},
                            {"subsystem": failover, "status": "ok",   "wan_ip": wan_ip},
                        ]
                    else:
                        # active_id matches primary, or it's unknown → assume primary
                        return [
                            {"subsystem": primary,  "status": "ok",   "wan_ip": wan_ip},
                            {"subsystem": failover, "status": "down", "wan_ip": ""},
                        ]
                else:
                    # mca-dump parsed but uplink has no IP → WAN is down
                    return [
                        {"subsystem": primary,  "status": "down", "wan_ip": ""},
                        {"subsystem": failover, "status": "down", "wan_ip": ""},
                    ]
        except Exception:
            pass

        # ── Strategy 2: ip route fallback (non-UCG/UDM devices) ─────────────
        try:
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
