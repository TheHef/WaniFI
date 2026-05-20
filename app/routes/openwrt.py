"""OpenWrt router settings and connection test endpoints."""
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..auth import require_auth
from ..db import get_setting, log_event, set_setting
from ..models import OpenWrtSettingsIn
from ..openwrt import OpenWrtClient

router = APIRouter(prefix="/api/openwrt")


@router.get("/settings")
async def get_openwrt_settings(_=Depends(require_auth)):
    return {
        "openwrt_url":            get_setting("openwrt_url", ""),
        "openwrt_username":       get_setting("openwrt_username", "root"),
        "openwrt_password_set":   bool(get_setting("openwrt_password")),
        "openwrt_primary_iface":  get_setting("openwrt_primary_iface", "wan"),
        "openwrt_failover_iface": get_setting("openwrt_failover_iface", "wwan"),
    }


@router.post("/settings")
async def save_openwrt_settings(payload: OpenWrtSettingsIn, _=Depends(require_auth)):
    set_setting("openwrt_url",            payload.openwrt_url.strip())
    set_setting("openwrt_username",       payload.openwrt_username.strip() or "root")
    if payload.openwrt_password:
        set_setting("openwrt_password",   payload.openwrt_password)
    set_setting("openwrt_primary_iface",  payload.openwrt_primary_iface.strip())
    set_setting("openwrt_failover_iface", payload.openwrt_failover_iface.strip())
    log_event("info", "OpenWrt settings updated")
    return {"ok": True}


@router.post("/test")
async def test_openwrt_connection(_=Depends(require_auth)):
    url      = get_setting("openwrt_url", "")
    username = get_setting("openwrt_username", "root")
    password = get_setting("openwrt_password", "")
    if not (url and password):
        return JSONResponse({"ok": False, "error": "Missing OpenWrt URL or password"}, status_code=400)
    client = OpenWrtClient(url, password, username)
    try:
        ok, msg = await client.test_connection()
        if not ok:
            return JSONResponse({"ok": False, "error": msg}, status_code=400)
        wan_ifaces = await client.get_wan_interfaces()
        return {
            "ok": True,
            "message": msg,
            "interfaces": [
                {
                    "interface": i.get("interface", ""),
                    "up":        i.get("up", False),
                    "ip":        (i.get("ipv4-address") or [{}])[0].get("address", ""),
                    "uptime":    i.get("uptime", 0),
                }
                for i in wan_ifaces
            ],
        }
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        await client.close()
