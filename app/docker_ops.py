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
