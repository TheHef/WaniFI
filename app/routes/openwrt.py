"""OpenWrt router settings and connection test endpoints."""
import httpx
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


@router.post("/debug")
async def debug_openwrt(_=Depends(require_auth)):
    url      = get_setting("openwrt_url", "")
    username = get_setting("openwrt_username", "root")
    password = get_setting("openwrt_password", "")
    result: dict = {"url": url, "username": username, "steps": []}

    if not url:
        result["steps"].append({"step": "config", "ok": False, "detail": "No URL configured"})
        return result
    if not password:
        result["steps"].append({"step": "config", "ok": False, "detail": "No password configured"})
        return result

    result["steps"].append({"step": "config", "ok": True, "detail": f"URL={url} user={username}"})

    # Step 1: raw HTTP reachability
    try:
        async with httpx.AsyncClient(verify=False, timeout=10) as http:
            r = await http.get(url)
            result["steps"].append({
                "step": "reachable", "ok": True,
                "detail": f"HTTP {r.status_code} — router is reachable",
            })
    except Exception as e:
        result["steps"].append({"step": "reachable", "ok": False, "detail": str(e)})
        return result

    # Step 2: raw auth call
    auth_url = url.rstrip("/") + "/cgi-bin/luci/rpc/auth"
    try:
        async with httpx.AsyncClient(verify=False, timeout=10) as http:
            r = await http.post(
                auth_url,
                json={"id": 1, "method": "login", "params": [username, password]},
            )
            body = r.json()
            token = body.get("result", "")
            auth_ok = bool(token and token.replace("0", ""))
            result["steps"].append({
                "step": "auth", "ok": auth_ok,
                "detail": f"HTTP {r.status_code} — result={token!r}",
                "raw": body,
            })
            if not auth_ok:
                return result
    except Exception as e:
        result["steps"].append({"step": "auth", "ok": False, "detail": str(e)})
        return result

    # Step 3: raw interface dump
    client = OpenWrtClient(url, password, username)
    try:
        ifaces = await client.get_interfaces()
        result["steps"].append({
            "step": "interfaces", "ok": bool(ifaces),
            "detail": f"{len(ifaces)} interface(s) returned",
            "raw": ifaces,
        })
    except Exception as e:
        result["steps"].append({"step": "interfaces", "ok": False, "detail": str(e)})
    finally:
        await client.close()

    return result
