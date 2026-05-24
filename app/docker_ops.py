"""Docker container operations via a shared SDK client."""
import time
from typing import Optional

import docker

from .config import log
from .models import VALID_ACTIONS  # single source of truth

_client: Optional[docker.DockerClient] = None


def _reset_client():
    global _client
    _client = None


def get_client() -> docker.DockerClient:
    global _client
    if _client is None:
        _client = docker.DockerClient(base_url="unix:///var/run/docker.sock")
    return _client


_docker_ok_cache: tuple[bool, float] = (False, 0.0)
_DOCKER_OK_TTL = 10.0


def docker_ok() -> bool:
    global _docker_ok_cache
    ok, ts = _docker_ok_cache
    if time.monotonic() - ts < _DOCKER_OK_TTL:
        return ok
    try:
        get_client().ping()
        _docker_ok_cache = (True, time.monotonic())
        return True
    except Exception:
        _reset_client()
        _docker_ok_cache = (False, time.monotonic())
        return False


_host_cmd_ok_cache: tuple[bool, float] = (False, 0.0)
_HOST_CMD_OK_TTL = 30.0


def host_command_ok() -> bool:
    """Return True if the container has both privileged + pid:host.

    Detected entirely from /proc/self/status — no subprocess needed:
    - CapEff must include CAP_SYS_ADMIN (bit 21) → privileged
    - NSpid must have exactly one value → pid:host (no nested PID namespace)
    """
    global _host_cmd_ok_cache
    ok, ts = _host_cmd_ok_cache
    if time.monotonic() - ts < _HOST_CMD_OK_TTL:
        return ok
    try:
        with open("/proc/self/status") as f:
            content = f.read()
        cap_eff = 0
        nspid_count = 2  # default to "nested" (not pid:host)
        for line in content.splitlines():
            if line.startswith("CapEff:"):
                cap_eff = int(line.split()[1], 16)
            elif line.startswith("NSpid:"):
                nspid_count = len(line.split()) - 1  # subtract label
        has_priv     = bool(cap_eff & (1 << 21))  # CAP_SYS_ADMIN
        has_pid_host = nspid_count == 1
        result = has_priv and has_pid_host
        _host_cmd_ok_cache = (result, time.monotonic())
        return result
    except Exception:
        _host_cmd_ok_cache = (False, time.monotonic())
        return False


def list_containers() -> list[dict]:
    try:
        containers = get_client().containers.list(all=True)
        return [
            {
                "name":   c.name,
                "id":     c.short_id,
                "status": c.status,
                "image":  c.image.tags[0] if c.image.tags else "",
            }
            for c in containers
        ]
    except Exception as e:
        _reset_client()
        log.error("Docker list failed: %s", e)
        return []


def container_action(name: str, action: str) -> tuple[bool, str]:
    if action not in VALID_ACTIONS:
        return False, f"Unknown action: {action}"
    try:
        c = get_client().containers.get(name)
        getattr(c, action)(**({"timeout": 5} if action in ("stop", "restart") else {}))
        return True, f"{action} OK"
    except docker.errors.NotFound:
        return False, f"Container {name!r} not found"
    except Exception as e:
        _reset_client()
        return False, str(e)
