"""qBittorrent settings and test endpoint."""
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..auth import require_auth
from ..db import get_setting, set_setting
from ..models import QbSettingsIn
from ..qbittorrent import QBittorrentClient

router = APIRouter(prefix="/api/qb-settings")
test_router = APIRouter()


@router.get("")
async def get_qb_settings(_: bool = Depends(require_auth)):
    return {
        "qb_url":          get_setting("qb_url", ""),
        "qb_username":     get_setting("qb_username", ""),
        "qb_password_set": bool(get_setting("qb_password")),
    }


@router.post("")
async def save_qb_settings(payload: QbSettingsIn, _: bool = Depends(require_auth)):
    set_setting("qb_url",      payload.qb_url.strip())
    set_setting("qb_username", payload.qb_username.strip())
    if payload.qb_password:
        set_setting("qb_password", payload.qb_password.strip())
    return {"ok": True}


@test_router.post("/api/test-qb")
async def api_test_qb(_: bool = Depends(require_auth)):
    url  = get_setting("qb_url", "")
    user = get_setting("qb_username", "")
    pw   = get_setting("qb_password", "")
    if not (url and user):
        return JSONResponse(
            {"ok": False, "error": "qBittorrent URL and username required"},
            status_code=400,
        )
    client = QBittorrentClient(url, user, pw or "")
    try:
        ok, err = await client.login()
        if ok:
            return {"ok": True}
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    finally:
        await client.close()
