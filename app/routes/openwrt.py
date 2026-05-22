"""OpenWrt router settings and connection test endpoints."""
import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..auth import require_auth
from ..db import get_setting, log_event, set_setting
from ..models import OpenWrtSettingsIn
from ..openwrt import OpenWrtClient

router = APIRouter(prefix="/api/openwrt")

_NULL_SESSION = "00000000000000000000000000000000"


@router.get("/settings")
async def get_openwrt_settings(_=Depends(require_auth)):
    return {
        "openwrt_url":            get_setting("openwrt_url", ""),
        "openwrt_username":       get_setting("openwrt_username", "root"),
        "openwrt_password_set":   bool(get_setting("openwrt_password")),
        "openwrt_primary_iface":  get_setting("openwrt_primary_iface", "wan"),
        "openwrt_failover_iface": get_setting("openwrt_failover_iface", "wwan"),
        "openwrt_router_model":   get_setting("openwrt_router_model", "OPENWRT"),
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
        all_ifaces  = await client.get_interfaces()
        wan_ifaces  = await client.get_wan_interfaces()
        from ..openwrt import _router_model
        model = _router_model(all_ifaces)
        set_setting("openwrt_router_model", model)
        return {
            "ok": True,
            "message": msg,
            "router_model": model,
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

    base = url.rstrip("/")
    token = None
    auth_mode = None

    # Step 2a: try native rpcd auth (/ubus)
    try:
        async with httpx.AsyncClient(verify=False, timeout=10) as http:
            r = await http.post(
                f"{base}/ubus",
                json={
                    "jsonrpc": "2.0", "id": 1, "method": "call",
                    "params": [_NULL_SESSION, "session", "login", {
                        "username": username, "password": password,
                    }],
                },
            )
            try:
                body = r.json()
                res = body.get("result")
                if isinstance(res, list) and res[0] == 0:
                    session = res[1].get("ubus_rpc_session", "")
                    if session and session.replace("0", ""):
                        token = session
                        auth_mode = "ubus"
                        result["steps"].append({
                            "step": "auth_ubus", "ok": True,
                            "detail": f"HTTP {r.status_code} — native ubus session OK, token={token[:8]}…",
                        })
                    else:
                        result["steps"].append({
                            "step": "auth_ubus", "ok": False,
                            "detail": f"HTTP {r.status_code} — got null/zero session (wrong password?)",
                            "raw": body,
                        })
                else:
                    result["steps"].append({
                        "step": "auth_ubus", "ok": False,
                        "detail": f"HTTP {r.status_code} — ubus error code {res[0] if isinstance(res, list) else 'N/A'}",
                        "raw": body,
                    })
            except Exception:
                result["steps"].append({
                    "step": "auth_ubus", "ok": False,
                    "detail": f"HTTP {r.status_code} — response is not JSON",
                    "raw_text": r.text[:300],
                })
    except Exception as e:
        result["steps"].append({"step": "auth_ubus", "ok": False, "detail": str(e)})

    # Step 2b: try LuCI RPC auth (/cgi-bin/luci/rpc/auth) — only if ubus auth failed
    if not token:
        try:
            async with httpx.AsyncClient(verify=False, timeout=10) as http:
                r = await http.post(
                    f"{base}/cgi-bin/luci/rpc/auth",
                    json={"id": 1, "method": "login", "params": [username, password]},
                )
                try:
                    body = r.json()
                    luci_token = body.get("result", "")
                    auth_ok = bool(luci_token and luci_token.replace("0", ""))
                    if auth_ok:
                        token = luci_token
                        auth_mode = "luci"
                    result["steps"].append({
                        "step": "auth_luci", "ok": auth_ok,
                        "detail": f"HTTP {r.status_code} — result={luci_token!r}",
                        "raw": body,
                    })
                except Exception:
                    result["steps"].append({
                        "step": "auth_luci", "ok": False,
                        "detail": f"HTTP {r.status_code} — response is not JSON",
                        "raw_text": r.text[:300],
                    })
        except Exception as e:
            result["steps"].append({"step": "auth_luci", "ok": False, "detail": str(e)})

    if not token:
        result["steps"].append({"step": "interfaces", "ok": False, "detail": "Skipped — no auth token"})
        return result

    result["steps"].append({"step": "auth_mode", "ok": True, "detail": f"Using mode={auth_mode}"})

    # Step 3: ubus call via whichever path authenticated
    try:
        async with httpx.AsyncClient(verify=False, timeout=10) as http:
            if auth_mode == "ubus":
                r = await http.post(
                    f"{base}/ubus",
                    json={
                        "jsonrpc": "2.0", "id": 1, "method": "call",
                        "params": [token, "network.interface", "dump", {}],
                    },
                )
            else:
                r = await http.post(
                    f"{base}/cgi-bin/luci/rpc/ubus",
                    json={
                        "jsonrpc": "2.0", "id": 1, "method": "call",
                        "params": [token, "network.interface", "dump", {}],
                    },
                    cookies={"sysauth": token, "sysauth_https": token},
                )
            try:
                ubus_body = r.json()
            except Exception:
                ubus_body = r.text[:500]
            ubus_result = ubus_body.get("result") if isinstance(ubus_body, dict) else None
            code = ubus_result[0] if isinstance(ubus_result, list) else None
            ifaces = ubus_result[1].get("interface", []) if isinstance(ubus_result, list) and code == 0 and isinstance(ubus_result[1], dict) else []
            result["steps"].append({
                "step": "interfaces",
                "ok": bool(ifaces),
                "detail": f"HTTP {r.status_code} — ubus code={code} — {len(ifaces)} interface(s)",
                "raw": ubus_body,
            })
    except Exception as e:
        result["steps"].append({"step": "interfaces", "ok": False, "detail": str(e)})

    return result


@router.get("/debug-list")
async def debug_openwrt_list(_=Depends(require_auth)):
    """List all available ubus services on the router."""
    url      = get_setting("openwrt_url", "")
    username = get_setting("openwrt_username", "root")
    password = get_setting("openwrt_password", "")
    if not (url and password):
        return JSONResponse({"ok": False, "error": "Not configured"}, status_code=400)

    client = OpenWrtClient(url, password, username)
    try:
        if not await client._auth():
            return JSONResponse({"ok": False, "error": "Auth failed"}, status_code=400)

        base = url.rstrip("/")
        import httpx
        async with httpx.AsyncClient(verify=False, timeout=10) as http:
            r = await http.post(
                f"{base}/ubus",
                json={"jsonrpc": "2.0", "id": 1, "method": "list", "params": ["*"]},
            )
            return {"ok": True, "mode": client._mode, "services": r.json()}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        await client.close()


@router.get("/debug-stats")
async def debug_openwrt_stats(_=Depends(require_auth)):
    """Show raw ubus data for each throughput source so we can diagnose 0 Mbps."""
    url      = get_setting("openwrt_url", "")
    username = get_setting("openwrt_username", "root")
    password = get_setting("openwrt_password", "")
    primary  = get_setting("openwrt_primary_iface", "wan")
    if not (url and password):
        return JSONResponse({"ok": False, "error": "Not configured"}, status_code=400)

    client = OpenWrtClient(url, password, username)
    try:
        if not await client._auth():
            return JSONResponse({"ok": False, "error": "Auth failed"}, status_code=400)

        ifaces = await client.get_interfaces()
        imap = {i["interface"]: i for i in ifaces}
        primary_obj = imap.get(primary, {})

        iface_status = await client.get_interface_status(primary)

        dev_name = primary_obj.get("device", "") or iface_status.get("device", "") or iface_status.get("l3_device", "")
        device_stats = await client.get_device_stats(dev_name) if dev_name else {}
        # Raw responses — show everything so we can find what works
        import httpx as _httpx
        base = url.rstrip("/")
        raw = {}
        for label, svc, method, params in [
            ("network_device_raw",    "network.device",  "status",          {"name": dev_name} if dev_name else {}),
            ("network_iface_raw",     f"network.interface.{primary}", "status", {}),
            ("luci_realtime_raw",     "luci",            "getRealtimeStats", {"device": dev_name, "mode": "network"} if dev_name else {}),
            ("luci_rpc_netdevs_raw",  "luci-rpc",        "getNetworkDevices", {}),
            ("gl_clients_speed_raw",  "gl-clients",      "get_speed",        {}),
            ("file_read_proc_raw",    "file",            "read",             {"path": "/proc/net/dev"}),
        ]:
            try:
                async with _httpx.AsyncClient(verify=False, timeout=8) as h:
                    r = await h.post(
                        f"{base}/ubus",
                        json={"jsonrpc": "2.0", "id": 1, "method": "call",
                              "params": [client._token, svc, method, params]},
                    )
                    raw[label] = r.json()
            except Exception as exc:
                raw[label] = {"error": str(exc)}

        return {"ok": True, "primary_iface": primary, "dev_name": dev_name, "raw_responses": raw}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        await client.close()
