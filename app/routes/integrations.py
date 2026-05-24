"""Integration enable/disable toggles."""
from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_auth
from ..db import get_setting, set_setting
from ..docker_ops import docker_ok, host_command_ok

router = APIRouter(prefix="/api/integrations")

INTEGRATION_KEYS = (
    "host_command", "docker", "webhook",
    "qb", "sabnzbd", "transmission", "deluge",
    "emby", "jellyfin", "plex",
    "ntfy", "discord", "telegram", "pushover",
    "homeassistant", "proxmox", "sonarr", "radarr",
    "pihole", "adguard",
    "portainer", "truenas", "unraid",
    "nodered", "nzbget", "gotify",
    "speedtest", "npm", "cloudflare", "nut",
)

# Always-on integrations: cannot be disabled by the user.
ALWAYS_ON = {"speedtest"}

# Auto-detected integrations: state is derived from runtime environment,
# not from user preference. The toggle is read-only.
AUTO_DETECT: dict = {
    "docker":       docker_ok,
    "host_command": host_command_ok,
}


@router.get("")
async def get_integrations(_: bool = Depends(require_auth)):
    result = {k: get_setting(f"integration_{k}", "0") == "1" for k in INTEGRATION_KEYS}
    for k in ALWAYS_ON:
        result[k] = True
    for k, fn in AUTO_DETECT.items():
        result[k] = fn()
    return result


@router.post("/{name}/toggle")
async def toggle_integration(name: str, _: bool = Depends(require_auth)):
    if name not in INTEGRATION_KEYS:
        raise HTTPException(400, f"Unknown integration: {name}")
    if name in ALWAYS_ON:
        return {"ok": True, "enabled": True}
    if name in AUTO_DETECT:
        # State is determined by runtime environment — return current value, no DB write.
        return {"ok": True, "enabled": AUTO_DETECT[name]()}
    current = get_setting(f"integration_{name}", "0")
    new_val = "0" if current == "1" else "1"
    set_setting(f"integration_{name}", new_val)
    return {"ok": True, "enabled": new_val == "1"}
