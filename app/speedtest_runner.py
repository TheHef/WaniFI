"""Speedtest integration — runs speedtest-cli in a thread pool and persists results."""
import asyncio
import json
import subprocess
import time
from typing import Optional

from .db import db, get_setting

_running = False


async def run_speedtest() -> tuple[bool, str]:
    """Run speedtest-cli, save to DB, return human-readable result."""
    global _running
    if _running:
        return False, "Speedtest already running"
    _running = True
    loop = asyncio.get_event_loop()
    try:
        server_id = get_setting("speedtest_server_id", "").strip()
        source_ip = get_setting("speedtest_source_ip", "").strip()
        cmd = ["speedtest-cli", "--json", "--secure"]
        if source_ip:
            cmd += ["--source", source_ip]
        if server_id:
            cmd += ["--server", server_id]

        result = await loop.run_in_executor(
            None, lambda c=cmd: subprocess.run(c, capture_output=True, text=True, timeout=120)
        )

        # If a specific server was configured but failed, retry with auto-select
        used_fallback = False
        if result.returncode != 0 and server_id:
            fallback_cmd = ["speedtest-cli", "--json", "--secure"]
            if source_ip:
                fallback_cmd += ["--source", source_ip]
            result = await loop.run_in_executor(
                None, lambda c=fallback_cmd: subprocess.run(
                    c, capture_output=True, text=True, timeout=120
                )
            )
            if result.returncode != 0:
                return False, f"Server #{server_id} failed, auto-select also failed: {result.stderr.strip() or 'speedtest-cli failed'}"
            used_fallback = True

        if result.returncode != 0:
            return False, result.stderr.strip() or "speedtest-cli failed"

        data = json.loads(result.stdout)
        dl     = round(data.get("download", 0) / 1_000_000, 1)
        ul     = round(data.get("upload", 0) / 1_000_000, 1)
        ping   = round(data.get("ping", 0), 1)
        isp    = data.get("client", {}).get("isp", "")
        server = data.get("server", {}).get("name", "")
        if used_fallback:
            server = f"{server} (auto-fallback — #{server_id} unavailable)"

        with db() as conn:
            conn.execute(
                "INSERT INTO speedtest_results (ts, download_mbps, upload_mbps, ping_ms, server, isp) VALUES (?,?,?,?,?,?)",
                (int(time.time()), dl, ul, ping, server, isp),
            )
            conn.execute(
                "DELETE FROM speedtest_results WHERE id NOT IN (SELECT id FROM speedtest_results ORDER BY ts DESC LIMIT 100)"
            )

        msg = f"↓ {dl} Mbps  ↑ {ul} Mbps  ping {ping} ms"
        if isp:
            msg += f"  via {isp}"
        if server:
            msg += f" ({server})"
        return True, msg

    except FileNotFoundError:
        return False, "speedtest-cli not found — rebuild the image to install it"
    except subprocess.TimeoutExpired:
        return False, "Speedtest timed out after 120 s"
    except json.JSONDecodeError as e:
        return False, f"Could not parse speedtest output: {e}"
    except Exception as e:
        return False, str(e)
    finally:
        _running = False


def get_last_speedtest() -> Optional[dict]:
    """Return the most recent speedtest result or None."""
    with db() as conn:
        row = conn.execute(
            "SELECT ts, download_mbps, upload_mbps, ping_ms, server, isp FROM speedtest_results ORDER BY ts DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    return {
        "ts":            row["ts"],
        "download_mbps": row["download_mbps"],
        "upload_mbps":   row["upload_mbps"],
        "ping_ms":       row["ping_ms"],
        "server":        row["server"],
        "isp":           row["isp"],
    }
