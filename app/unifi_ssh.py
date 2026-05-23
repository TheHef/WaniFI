"""UniFi SSH client — collects WAN/gateway data via SSH as an alternative to the API key."""
import asyncio
import json
import time
from typing import Optional
from urllib.parse import urlparse

from .config import log
from .db import get_setting

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
        # Cache for adopted-device list (refreshed every 120 s to avoid hitting
        # MongoDB on every live-stats poll without being permanently stale).
        self._adopted_cache: Optional[tuple[float, list[dict], str]] = None

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

    # ── Device discovery helpers (all read-only) ────────────────────────────

    async def _query_adopted_devices(self) -> list[dict]:
        """Read adopted UniFi device records from local MongoDB (read-only find).

        Tries mongosh (UniFi OS 3+ / MongoDB 6+) then the older mongo client.
        Returns a list of {model, name, mac, ip} dicts — one per adopted device.
        """
        # Both commands are SELECT-equivalent (find with projection, no writes).
        js_expr = (
            "db.device.find({},"
            "{model:1,name:1,mac:1,ip:1,_id:0})"
            ".forEach(d=>print(JSON.stringify(d)))"
        )
        cmds = [
            f"mongosh --quiet localhost/ace --eval '{js_expr}' 2>/dev/null",
            f"mongo    --quiet localhost/ace --eval '{js_expr}' 2>/dev/null",
        ]
        for cmd in cmds:
            try:
                out = await self._run(cmd)
                if not out:
                    continue
                devices: list[dict] = []
                for line in out.splitlines():
                    line = line.strip()
                    if not line.startswith("{"):
                        continue          # skip mongosh banner / warnings
                    try:
                        d = json.loads(line)
                        if d.get("model"):
                            devices.append({
                                "model": d.get("model", ""),
                                "name":  d.get("name",  ""),
                                "mac":   d.get("mac",   ""),
                                "ip":    d.get("ip",    ""),
                            })
                    except Exception:
                        pass
                if devices:
                    return devices
            except Exception:
                pass
        return []

    async def _get_gre_remotes(self) -> dict[str, str]:
        """Read GRE tunnel remote IPs via 'ip tunnel show' (read-only).

        Returns {linux_iface_name: remote_ip}, e.g. {"gre1": "192.168.0.50"}.
        The remote IP is the LAN-side address of the device (e.g. U5G-Max)
        that terminates the tunnel on the other end.
        """
        result: dict[str, str] = {}
        try:
            text = await self._run("ip tunnel show 2>/dev/null")
            for line in text.splitlines():
                # e.g.: gre1: gre remote 192.168.0.50 local 192.168.0.1 dev eth0 …
                parts = line.split()
                if not parts:
                    continue
                iface = parts[0].rstrip(":")
                if "remote" in parts:
                    idx = parts.index("remote")
                    if idx + 1 < len(parts):
                        remote = parts[idx + 1]
                        if remote and remote != "any":
                            result[iface] = remote
        except Exception:
            pass
        return result

    async def _probe_device_at(self, ip: str) -> dict:
        """SSH into a secondary UniFi device to read its model and hostname.

        Read-only: only reads /proc/ubnthal/system_info and hostname.

        Strategy 1 (preferred): run ``ssh`` from the gateway shell.
        UniFi OS installs pre-shared SSH keys between the gateway and every
        adopted device, so the gateway can SSH in without a password.
        This works even when the target's management IP is on an internal
        subnet unreachable from the WaniFi host (e.g. 192.168.50.2).

        Strategy 2 (fallback): asyncssh direct-tcpip channel through the
        already-open gateway connection (jump-host proxy), using the shared
        SSH password.  Requires AllowTcpForwarding on the gateway's sshd.

        Returns {model, name, ip} — fields may be empty on any SSH failure.
        """
        result: dict = {"model": "", "name": "", "ip": ip}
        if not _HAS_ASYNCSSH:
            return result

        # The remote command — no single quotes so it's safe inside either
        # double-quoted shell argument or passed directly via asyncssh.
        remote_cmd = (
            "cat /proc/ubnthal/system_info 2>/dev/null; "
            "echo ---HOSTNAME---; "
            "hostname 2>/dev/null"
        )
        raw = ""

        # ── Strategy 1: ssh client on the gateway shell ──────────────────────
        # UniFi OS pre-installs host keys for inter-device management, so the
        # gateway can usually SSH into any adopted device without a password.
        # We suppress stderr (2>/dev/null) so a connection failure just returns
        # empty output rather than raising an exception.
        try:
            shell_cmd = (
                f"ssh -o StrictHostKeyChecking=no "
                f"-o ConnectTimeout=5 "
                f"-o BatchMode=yes "
                f"-p {self._port} "
                f'{self._username}@{ip} "{remote_cmd}" 2>/dev/null'
            )
            out = await self._run(shell_cmd)
            if out and "---HOSTNAME---" in out:
                raw = out
                log.debug("SSH probe (shell) succeeded for %s", ip)
        except Exception as e:
            log.debug("SSH probe (shell) failed for %s: %s", ip, e)

        # ── Strategy 2: asyncssh direct-tcpip (jump host) ────────────────────
        # Use the already-open gateway connection as a TCP tunnel so the target
        # device does not need to be directly reachable from WaniFi.
        # Requires AllowTcpForwarding on the gateway's sshd.
        if not raw:
            try:
                await self._ensure_connected()
                conn = await asyncssh.connect(
                    ip,
                    port=self._port,
                    username=self._username,
                    password=self._password,
                    known_hosts=None,
                    connect_timeout=8,
                    tunnel=self._conn,
                )
                try:
                    r = await conn.run(remote_cmd, check=False, timeout=10)
                    raw = (r.stdout or "").strip()
                    if raw:
                        log.debug("SSH probe (jump host) succeeded for %s", ip)
                finally:
                    conn.close()
            except Exception as e:
                log.debug("SSH probe (jump host) failed for %s: %s", ip, e)

        if not raw:
            return result

        # ── Parse output ─────────────────────────────────────────────────────
        if "---HOSTNAME---" in raw:
            info_part, _, host_part = raw.partition("---HOSTNAME---")
        else:
            info_part, host_part = raw, ""

        # Parse key=value lines from /proc/ubnthal/system_info
        # Common keys: shortname, name, board_name, systemid
        fields: dict[str, str] = {}
        for line in info_part.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                fields[k.strip().lower()] = v.strip()

        model = (
            fields.get("shortname") or
            fields.get("name")      or
            fields.get("board_name") or
            ""
        )
        hostname = host_part.strip().splitlines()[0] if host_part.strip() else ""

        if model:
            result["model"] = model
        if hostname:
            result["name"] = hostname

        return result

    async def _query_ulp_backup_file(self) -> list[dict]:
        """Read /data/ulp-go/ws/backup_unifi_devices.json and return device records.

        The UniFi Location Platform (ulp-go) service writes this backup file on
        UCG-Max devices. It contains adopted device data (model, name, ip, mac)
        and is readable without credentials — useful when MongoDB is not running
        and secondary devices block SSH entirely.

        Returns list of {model, name, mac, ip} dicts.
        """
        try:
            raw = await self._run(
                "cat /data/ulp-go/ws/backup_unifi_devices.json 2>/dev/null"
            )
            if not raw or not ("{" in raw or "[" in raw):
                return []
            data = json.loads(raw)
        except Exception:
            return []

        # Normalise: may be a bare list or wrapped in a dict key
        entries: list = []
        if isinstance(data, list):
            entries = data
        elif isinstance(data, dict):
            for key in ("data", "devices", "device_list", "list"):
                val = data.get(key)
                if isinstance(val, list):
                    entries = val
                    break
            if not entries and data.get("model"):
                entries = [data]

        devices: list[dict] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            model = (
                entry.get("model") or
                entry.get("device_type") or
                ""
            )
            name = (
                entry.get("name") or
                entry.get("hostname") or
                entry.get("alias") or
                ""
            )
            ip = (
                entry.get("ip") or
                entry.get("ip_addr") or
                entry.get("ipAddress") or
                ""
            )
            mac = (
                entry.get("mac") or
                entry.get("macAddress") or
                ""
            )
            if model or mac:
                devices.append({"model": model, "name": name, "mac": mac, "ip": ip})
        return devices

    async def _get_extra_devices_cached(self, gw_model: str, gw_name: str) -> list[dict]:
        """Return non-gateway WAN devices with a 120 s TTL cache.

        Strategy 1: local MongoDB find() — works on some UniFi OS versions.
        Strategy 2: SSH probe each GRE tunnel remote IP directly using the same
          credentials (UniFi shares SSH password across all adopted devices).
          Reads /proc/ubnthal/system_info → model, hostname, and the LAN IP
          is taken from the tunnel remote address.
        Strategy 3: read /data/ulp-go/ws/backup_unifi_devices.json — present on
          UCG-Max; does not require MongoDB or SSH access to secondary devices.

        Returns list of {model, name, ip} dicts.
        """
        now = time.monotonic()
        override_model = get_setting("gre_device_model", "")
        if (self._adopted_cache is not None
                and now - self._adopted_cache[0] <= 120
                and self._adopted_cache[2] == override_model):
            return self._adopted_cache[1]

        extra: list[dict] = []

        # Strategy 1: MongoDB (may not be available on all UniFi OS versions)
        adopted = await self._query_adopted_devices()
        if adopted:
            extra = [
                d for d in adopted
                if not (d.get("model") == gw_model and d.get("name") == gw_name)
            ]
            if not extra and len(adopted) > 1:
                extra = [d for d in adopted if d.get("name") != gw_name]

        # Strategy 2: SSH into each GRE tunnel remote IP with the same credentials.
        # The remote IP from 'ip tunnel show' is the device's LAN management IP,
        # so we can SSH directly to it and read /proc/ubnthal/system_info.
        if not extra:
            gre_remotes = await self._get_gre_remotes()
            if gre_remotes:
                probes = await asyncio.gather(
                    *[self._probe_device_at(ip) for ip in gre_remotes.values()],
                    return_exceptions=True,
                )
                for probe in probes:
                    if isinstance(probe, dict) and (probe.get("model") or probe.get("name")):
                        extra.append(probe)

        # Strategy 3: ULP backup file (UCG-Max specific, read-only cat).
        # Skipped if Strategy 1/2 already found devices.
        if not extra:
            ulp_devices = await self._query_ulp_backup_file()
            if ulp_devices:
                extra = [
                    d for d in ulp_devices
                    if not (d.get("model") == gw_model and d.get("name") == gw_name)
                ]

        # Strategy 4: manual override from Settings UI.
        # Used when all automated discovery fails (e.g. MongoDB not running,
        # secondary device ports closed, ULP file empty).
        if not extra and override_model:
            gre_remotes = await self._get_gre_remotes()
            if gre_remotes:
                extra = [
                    {"model": override_model, "name": override_model, "ip": ip}
                    for ip in gre_remotes.values()
                ]
            else:
                extra = [{"model": override_model, "name": override_model, "ip": ""}]

        self._adopted_cache = (now, extra, override_model)
        return extra

    # ── Public API (shape-compatible with UniFiClient) ───────────────────────

    async def discover_wans(self) -> list[dict]:
        """Return WAN interface list in the same format as the /api/test-unifi endpoint.

        Each entry:
          subsystem    – lowercase WAN name used in settings ("wan", "wan3", …)
          status       – "ok" or "down"
          wan_ip       – current WAN IP
          isp_name     – ISP name from geo_info if available
          active       – True for the currently active uplink
          device_model – model of the device providing this WAN
          device_name  – name/hostname of the device providing this WAN

        Device attribution logic:
          - Native ethernet/SFP ports (eth*, sfp*) → the gateway itself
          - GRE tunnel interfaces (gre*) → match by remote IP against MongoDB
            adopted-device records; fall back to first non-gateway adopted device
          - Other non-native interfaces → first unmatched adopted device
        """
        try:
            mca_text = await self._run("mca-dump 2>/dev/null")
            if not (mca_text and "{" in mca_text):
                return []
            data = json.loads(mca_text.replace("\x00", ""))
        except Exception:
            return []

        uplink_raw    = data.get("uplink", "")
        if_table:     list[dict] = data.get("if_table")    or []
        geo_info:     dict       = data.get("geo_info")    or {}
        uptime_stats: dict       = data.get("uptime_stats") or {}
        gw_model = data.get("model", "")
        gw_name  = data.get("hostname") or data.get("name", "")

        # ── Older UDM layout (uplink is a dict, no if_table) ─────────────────
        if not if_table:
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

        # ── UCG-Max layout: WAN interfaces from if_table ──────────────────────
        wan_ifaces = [
            i for i in if_table
            if (i.get("comment") or "").upper().startswith("WAN")
        ]

        # Determine which WAN interfaces use non-native Linux interfaces
        # (GRE tunnels etc.) so we only run the extra SSH reads when needed.
        has_gre = any(
            (i.get("name") or "").startswith("gre") for i in wan_ifaces
        )
        has_non_native = any(
            not (i.get("name") or "").startswith(("eth", "sfp"))
            for i in wan_ifaces
        )

        # Fetch extra (non-gateway) WAN devices via the cached resolution strategy:
        #   Strategy 1: local MongoDB find() (may not be available on all OS versions)
        #   Strategy 2: SSH probe each GRE tunnel remote IP using the same credentials
        # gre_remotes is fetched separately so the attribution loop below can match
        # by remote IP even when extra_adopted was built from SSH probes.
        extra_adopted: list[dict] = []
        gre_remotes: dict[str, str] = {}
        if has_non_native:
            extra_adopted = await self._get_extra_devices_cached(gw_model, gw_name)
        if has_gre:
            gre_remotes = await self._get_gre_remotes()

        result: list[dict] = []
        for iface in wan_ifaces:
            comment    = iface.get("comment", "")   # "WAN", "WAN3", …
            linux_name = iface.get("name",    "")   # "eth4", "gre1", …
            name_lower = comment.lower()             # "wan", "wan3", …

            is_active = isinstance(uplink_raw, str) and linux_name == uplink_raw

            # Status: prefer uptime_stats (reliable), else if_table "up" flag
            status = "down"
            if comment in uptime_stats:
                avail  = uptime_stats[comment].get("availability", 0)
                status = "ok" if avail and avail >= 100.0 else "down"
            elif iface.get("up"):
                status = "ok"

            # ISP name from geo_info
            isp_name: Optional[str] = None
            if comment in geo_info:
                isp_name = geo_info[comment].get("isp_name")

            # ── Device attribution ────────────────────────────────────────────
            dev_model = gw_model
            dev_name  = gw_name

            if linux_name.startswith(("eth", "sfp")):
                # Physical port on the gateway itself — no lookup needed
                pass

            elif linux_name.startswith("gre") and extra_adopted:
                # GRE tunnel → try to match remote IP to an adopted device's IP
                remote_ip = gre_remotes.get(linux_name, "")
                matched = next(
                    (d for d in extra_adopted if d.get("ip") == remote_ip),
                    None,
                )
                if matched is None:
                    # No IP match (e.g. GRE over public IP / CGNAT) →
                    # use the first unmatched extra device
                    matched = extra_adopted[0]
                if matched:
                    dev_model = matched.get("model", "") or gw_model
                    dev_name  = matched.get("name",  "") or gw_name
                    # Remove so the same device isn't assigned to two WANs
                    if matched in extra_adopted:
                        extra_adopted.remove(matched)

            elif extra_adopted:
                # Other non-native interface (PPPoE, VLAN, …)
                matched = extra_adopted.pop(0)
                dev_model = matched.get("model", "") or gw_model
                dev_name  = matched.get("name",  "") or gw_name

            result.append({
                "subsystem":    name_lower,
                "status":       status,
                "wan_ip":       iface.get("ip", ""),
                "isp_name":     isp_name,
                "active":       is_active,
                "device_model": dev_model,
                "device_name":  dev_name,
            })

        return result

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
                geo_info: dict       = data.get("geo_info")  or {}
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
                            # Resolve IP and ISP from if_table / geo_info
                            wan_ip   = ""
                            isp_name: Optional[str] = (geo_info.get(matched_key) or {}).get("isp_name")
                            for iface in if_table:
                                if (iface.get("comment") or "").lower() == matched_key.lower():
                                    wan_ip = iface.get("ip", "")
                                    break
                            health.append({
                                "subsystem": wan_key,
                                "status":    status,
                                "wan_ip":    wan_ip,
                                "isp_name":  isp_name,
                            })
                        else:
                            health.append({"subsystem": wan_key, "status": "down", "wan_ip": "", "isp_name": None})
                    return health

                # No uptime_stats — fall back to uplink string / ip field
                if isinstance(uplink_raw, str) and if_table:
                    active_iface = next(
                        (i for i in if_table if i.get("name") == uplink_raw), None
                    )
                    if active_iface:
                        active_comment = (active_iface.get("comment") or "").lower()
                        wan_ip   = active_iface.get("ip", "")
                        isp_p    = (geo_info.get(primary.upper())  or {}).get("isp_name")
                        isp_f    = (geo_info.get(failover.upper()) or {}).get("isp_name")
                        if active_comment == failover.lower():
                            return [
                                {"subsystem": primary,  "status": "down", "wan_ip": "",     "isp_name": isp_p},
                                {"subsystem": failover, "status": "ok",   "wan_ip": wan_ip, "isp_name": isp_f},
                            ]
                        else:
                            return [
                                {"subsystem": primary,  "status": "ok",   "wan_ip": wan_ip, "isp_name": isp_p},
                                {"subsystem": failover, "status": "down", "wan_ip": "",     "isp_name": isp_f},
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
                                {"subsystem": primary,  "status": "down", "wan_ip": "",     "isp_name": None},
                                {"subsystem": failover, "status": "ok",   "wan_ip": wan_ip, "isp_name": None},
                            ]
                        return [
                            {"subsystem": primary,  "status": "ok",   "wan_ip": wan_ip, "isp_name": None},
                            {"subsystem": failover, "status": "down", "wan_ip": "",     "isp_name": None},
                        ]
                    else:
                        return [
                            {"subsystem": primary,  "status": "down", "wan_ip": "", "isp_name": None},
                            {"subsystem": failover, "status": "down", "wan_ip": "", "isp_name": None},
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
                    # Populate extra_devices from adopted-device cache (120 s TTL)
                    # so the failover WAN card shows the correct device model/name
                    # (e.g. U5G-Max instead of UCG-Max) without a MongoDB round-trip
                    # on every live-stats tick.
                    try:
                        extras = await self._get_extra_devices_cached(
                            parsed.get("gw_model", ""),
                            parsed.get("gw_name",  ""),
                        )
                        parsed["extra_devices"] = [
                            {
                                "model": d.get("model", ""),
                                "name":  d.get("name",  ""),
                                "ip":    d.get("ip",    ""),
                            }
                            for d in extras
                        ]
                    except Exception:
                        pass   # keep extra_devices: [] on any error
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
