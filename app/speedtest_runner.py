"""Speedtest integration — runs speedtest-cli in a thread pool."""
import asyncio
import subprocess
import json


async def run_speedtest() -> tuple[bool, str]:
    """Run speedtest-cli and return a human-readable result string."""
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["speedtest-cli", "--json", "--secure"],
                capture_output=True,
                text=True,
                timeout=120,
            ),
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() or "speedtest-cli failed"
            return False, stderr

        data = json.loads(result.stdout)
        dl   = round(data.get("download", 0) / 1_000_000, 1)
        ul   = round(data.get("upload", 0) / 1_000_000, 1)
        ping = round(data.get("ping", 0), 1)
        isp  = data.get("client", {}).get("isp", "")
        server = data.get("server", {}).get("name", "")
        msg = f"↓ {dl} Mbps  ↑ {ul} Mbps  ping {ping} ms"
        if isp:
            msg += f"  via {isp}"
        if server:
            msg += f" ({server})"
        return True, msg
    except FileNotFoundError:
        return False, "speedtest-cli not found — add 'speedtest-cli' to requirements.txt and rebuild"
    except subprocess.TimeoutExpired:
        return False, "Speedtest timed out after 120 s"
    except json.JSONDecodeError as e:
        return False, f"Could not parse speedtest output: {e}"
    except Exception as e:
        return False, str(e)
