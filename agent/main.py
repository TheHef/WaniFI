"""WaniFi Agent — connects to WaniFi server and executes commands remotely."""
import asyncio
import json
import logging
import os
import shlex
import subprocess
import time

import docker
import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("wanifi-agent")

WANIFI_URL: str = os.environ["WANIFI_URL"].rstrip("/")   # e.g. wss://wanifi.example.com
AGENT_KEY:  str = os.environ["AGENT_API_KEY"]
RECONNECT_DELAY = 10  # seconds between reconnect attempts

WS_URL = WANIFI_URL.replace("http://", "ws://").replace("https://", "wss://") + "/api/agents/ws?key=" + os.environ["AGENT_API_KEY"]

_docker_client = None


def get_docker():
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.DockerClient(base_url="unix:///var/run/docker.sock")
    return _docker_client


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def handle_ping() -> dict:
    return {"ok": True, "pong": True, "ts": int(time.time())}


def handle_docker(action: str, container: str) -> dict:
    valid = {"start", "stop", "restart", "pause", "unpause"}
    if action not in valid:
        return {"ok": False, "error": f"Unknown docker action: {action}"}
    try:
        c = get_docker().containers.get(container)
        kwargs = {"timeout": 5} if action in ("stop", "restart") else {}
        getattr(c, action)(**kwargs)
        return {"ok": True, "message": f"{action} {container!r} OK"}
    except docker.errors.NotFound:
        return {"ok": False, "error": f"Container {container!r} not found"}
    except Exception as e:
        global _docker_client
        _docker_client = None
        return {"ok": False, "error": str(e)}


def handle_host_command(command: str) -> dict:
    if not command.strip():
        return {"ok": False, "error": "Empty command"}
    try:
        result = subprocess.run(
            shlex.split(command),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Command timed out after 30s"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def dispatch(msg: dict) -> dict:
    cmd_type = msg.get("type", "")
    if cmd_type == "ping":
        return handle_ping()
    if cmd_type == "docker":
        return handle_docker(msg.get("action", ""), msg.get("container", ""))
    if cmd_type == "host_command":
        return handle_host_command(msg.get("command", ""))
    return {"ok": False, "error": f"Unknown command type: {cmd_type!r}"}


# ---------------------------------------------------------------------------
# WebSocket loop
# ---------------------------------------------------------------------------

async def run():
    while True:
        try:
            log.info("Connecting to %s", WS_URL)
            async with websockets.connect(WS_URL) as ws:
                log.info("Connected to WaniFi server")
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        log.info("Received command: %s", msg.get("type"))
                        result = dispatch(msg)
                        await ws.send(json.dumps(result))
                        log.info("Result: %s", result)
                    except Exception as e:
                        log.error("Error handling command: %s", e)
                        await ws.send(json.dumps({"ok": False, "error": str(e)}))
        except Exception as e:
            log.warning("Connection lost: %s — reconnecting in %ds", e, RECONNECT_DELAY)
            await asyncio.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    asyncio.run(run())
