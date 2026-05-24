"""WaniFi Agent — connects to WaniFi server and executes commands remotely."""
import asyncio
import json
import logging
import os
import shlex
import socket
import subprocess
import time

import docker
import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("wanifi-agent")

WANIFI_URL: str = os.environ["WANIFI_URL"].rstrip("/")   # e.g. wss://wanifi.example.com
AGENT_KEY:  str = os.environ["AGENT_API_KEY"]

def _read_version() -> str:
    """Read baked-in git SHA from /app/VERSION, fall back to env var or 'dev'."""
    try:
        v = open("/app/VERSION").read().strip()
        if v and v != "dev":
            return v[:7]  # short SHA
    except Exception:
        pass
    return os.environ.get("AGENT_VERSION", "dev")

AGENT_VERSION: str = _read_version()
RECONNECT_DELAY = 10  # seconds between reconnect attempts

WS_URL = WANIFI_URL.replace("http://", "ws://").replace("https://", "wss://") + "/api/agents/ws"

_docker_client = None


def get_docker():
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.DockerClient(base_url="unix:///var/run/docker.sock")
    return _docker_client


def detect_caps() -> dict:
    """Auto-detect runtime capabilities to report to the WaniFi server."""
    # Docker: try to ping the socket
    docker_ok = False
    try:
        c = docker.DockerClient(base_url="unix:///var/run/docker.sock")
        c.ping()
        docker_ok = True
    except Exception:
        pass

    # Host command: requires privileged (CAP_SYS_ADMIN) + pid:host (NSpid count == 1)
    host_command_ok = False
    try:
        with open("/proc/self/status") as f:
            content = f.read()
        cap_eff = 0
        nspid_count = 2
        for line in content.splitlines():
            if line.startswith("CapEff:"):
                cap_eff = int(line.split()[1], 16)
            elif line.startswith("NSpid:"):
                nspid_count = len(line.split()) - 1
        host_command_ok = bool(cap_eff & (1 << 21)) and nspid_count == 1
    except Exception:
        pass

    # Hostname
    hostname = ""
    try:
        hostname = socket.gethostname()
    except Exception:
        pass

    # Host IP — three methods tried in order:
    # 1. nsenter: run `ip route get` inside host's network namespace (most reliable)
    # 2. fib_trie: parse /proc/1/net/fib_trie (works with pid:host, no extra tools)
    # 3. UDP trick: container's own outbound IP (fallback)
    ip = ""

    # Method 1: nsenter (requires util-linux + iproute2 in image)
    if not ip:
        try:
            r = subprocess.run(
                ["nsenter", "-t", "1", "-n", "--", "ip", "route", "get", "8.8.8.8"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                tokens = r.stdout.split()
                for i, tok in enumerate(tokens):
                    if tok == "src" and i + 1 < len(tokens):
                        candidate = tokens[i + 1]
                        try:
                            socket.inet_aton(candidate)
                            ip = candidate
                        except Exception:
                            pass
                        break
        except Exception:
            pass

    # Method 2: parse /proc/1/net/fib_trie (host network namespace via pid:host)
    if not ip:
        try:
            candidates = []
            prev_ip = None
            with open("/proc/1/net/fib_trie") as f:
                for line in f:
                    s = line.strip()
                    if s.startswith("-- "):
                        candidate = s[3:].split("/")[0].strip()
                        try:
                            socket.inet_aton(candidate)
                            prev_ip = candidate
                        except Exception:
                            prev_ip = None
                    elif "/32 host LOCAL" in s and prev_ip:
                        if not prev_ip.startswith("127.") and not prev_ip.startswith("0."):
                            candidates.append(prev_ip)
                        prev_ip = None
            # Skip Docker bridge range (172.16–31.x.x) and link-local
            for candidate in candidates:
                parts = candidate.split(".")
                if parts[0] == "172" and 16 <= int(parts[1]) <= 31:
                    continue
                if candidate.startswith("169.254."):
                    continue
                ip = candidate
                break
            if not ip and candidates:
                ip = candidates[0]
        except Exception:
            pass

    # Method 3: UDP trick — gives the container's own outbound IP
    if not ip:
        try:
            _s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            _s.settimeout(2)
            _s.connect(("8.8.8.8", 80))
            ip = _s.getsockname()[0]
            _s.close()
        except Exception:
            pass

    return {
        "docker":       docker_ok,
        "host_command": host_command_ok,
        "hostname":     hostname,
        "ip":           ip,
        "version":      AGENT_VERSION,
    }


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


_MAX_OUTPUT = 4096


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
            "stdout": result.stdout.strip()[:_MAX_OUTPUT],
            "stderr": result.stderr.strip()[:_MAX_OUTPUT],
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Command timed out after 30s"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def handle_list_containers() -> dict:
    try:
        cs = get_docker().containers.list(all=True)
        return {"ok": True, "containers": [{"name": c.name, "status": c.status} for c in cs]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def dispatch(msg: dict) -> dict:
    cmd_type = msg.get("type", "")
    if cmd_type == "ping":
        return handle_ping()
    if cmd_type == "list_containers":
        return handle_list_containers()
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
            log.info("Connecting to WaniFi server")
            async with websockets.connect(WS_URL) as ws:
                # Detect capabilities and authenticate
                caps = detect_caps()
                log.info("Caps: docker=%s host_command=%s ip=%s hostname=%s version=%s",
                         caps["docker"], caps["host_command"], caps["ip"],
                         caps["hostname"], caps["version"])
                await ws.send(json.dumps({"type": "auth", "key": AGENT_KEY, "caps": caps}))
                ack = json.loads(await ws.recv())
                if not ack.get("ok"):
                    log.error("Authentication rejected: %s", ack.get("error", "unknown"))
                    await asyncio.sleep(RECONNECT_DELAY)
                    continue
                log.info("Authenticated and connected")
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
