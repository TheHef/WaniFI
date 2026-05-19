"""Speedtest integration — uses Ookla speedtest CLI for accurate multi-gigabit results."""
import asyncio
import json
import subprocess
import time
from typing import Optional

from .db import db, get_setting

_running = False


def _parse_ookla(data: dict) -> tuple[float, float, float, str, str]:
    """Parse Ookla CLI JSON output. bandwidth is bytes/sec → convert to Mbps."""
    dl     = round(data["download"]["bandwidth"] * 8 / 1_000_000, 1)
    ul     = round(data["upload"]["bandwidth"] * 8 / 1_000_000, 1)
    ping   = round(data["ping"]["latency"], 1)
    isp    = data.get("isp", "")
    server = data.get("server", {}).get("name", "") or data.get("server", {}).get("location", "")
    return dl, ul, ping, isp, server


async def run_speedtest() -> tuple[bool, str]:
    """Run Ookla speedtest CLI, save to DB, return human-readable result."""
    global _running
    if _running:
        return False, "Speedtest already running"
    _running = True
    loop = asyncio.get_event_loop()
    try:
        server_id = get_setting("speedtest_server_id", "").strip()

        # Ookla CLI flags: --accept-license/--accept-gdpr suppress interactive prompts
        cmd = ["speedtest", "--format=json", "--accept-license", "--accept-gdpr"]
        if server_id:
            cmd += ["--server-id", server_id]

        result = await loop.run_in_executor(
            None, lambda c=cmd: subprocess.run(c, capture_output=True, text=True, timeout=120)
        )

        # If configured server failed, retry with auto-select
        used_fallback = False
        if result.returncode != 0 and server_id:
            fallback_cmd = ["speedtest", "--format=json", "--accept-license", "--accept-gdpr"]
            result = await loop.run_in_executor(
                None, lambda c=fallback_cmd: subprocess.run(c, capture_output=True, text=True, timeout=120)
            )
            if result.returncode != 0:
                return False, f"Server #{server_id} failed, auto-select also failed: {result.stderr.strip() or 'speedtest failed'}"
            used_fallback = True

        if result.returncode != 0:
            return False, result.stderr.strip() or "speedtest failed"

        # Ookla CLI outputs multiple JSON lines; the result line has "type":"result"
        data = None
        for line in result.stdout.splitlines():
            try:
                obj = json.loads(line)
                if obj.get("type") == "result":
                    data = obj
                    break
            except json.JSONDecodeError:
                continue
        if data is None:
            data = json.loads(result.stdout)  # fallback: single JSON object

        dl, ul, ping, isp, server = _parse_ookla(data)
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
        return False, "Ookla speedtest not found — rebuild the Docker image"
    except subprocess.TimeoutExpired:
        return False, "Speedtest timed out after 120 s"
    except (json.JSONDecodeError, KeyError) as e:
        return False, f"Could not parse speedtest output: {e}\n{result.stdout[:200] if 'result' in dir() else ''}"
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
