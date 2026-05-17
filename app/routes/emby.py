"""Emby settings and test endpoint."""
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..auth import require_auth
from ..db import get_setting, set_setting
from ..emby import EmbyClient
from ..models import EmbySettingsIn

router = APIRouter(prefix="/api/emby-settings")
test_router = APIRouter()


@router.get("")
async def get_emby_settings(_: bool = Depends(require_auth)):
    return {
        "emby_url":       get_setting("emby_url", ""),
        "emby_token_set": bool(get_setting("emby_token")),
    }


@router.post("")
async def save_emby_settings(payload: EmbySettingsIn, _: bool = Depends(require_auth)):
    set_setting("emby_url", payload.emby_url.strip())
    if payload.emby_token:
        set_setting("emby_token", payload.emby_token.strip())
    return {"ok": True}


@test_router.post("/api/test-emby")
async def api_test_emby(_: bool = Depends(require_auth)):
    url   = get_setting("emby_url", "")
    token = get_setting("emby_token", "")
    if not (url and token):
        return JSONResponse(
            {"ok": False, "error": "Emby URL and API token required"},
            status_code=400,
        )
    client = EmbyClient(url, token)
    try:
        ok, msg = await client.test()
        if ok:
            return {"ok": True, "message": msg}
        return JSONResponse({"ok": False, "error": msg}, status_code=400)
    finally:
        await client.close()
