"""Integration enable/disable toggles."""
from fastapi import APIRouter, Depends

from ..auth import require_auth
from ..db import get_setting, set_setting

router = APIRouter(prefix="/api/integrations")

INTEGRATION_KEYS = ("docker", "qb", "emby", "ntfy")


@router.get("")
async def get_integrations(_: bool = Depends(require_auth)):
    return {k: get_setting(f"integration_{k}", "1") == "1" for k in INTEGRATION_KEYS}


@router.post("/{name}/toggle")
async def toggle_integration(name: str, _: bool = Depends(require_auth)):
    if name not in INTEGRATION_KEYS:
        from fastapi import HTTPException
        raise HTTPException(400, f"Unknown integration: {name}")
    current = get_setting(f"integration_{name}", "1")
    new_val = "0" if current == "1" else "1"
    set_setting(f"integration_{name}", new_val)
    return {"ok": True, "enabled": new_val == "1"}
