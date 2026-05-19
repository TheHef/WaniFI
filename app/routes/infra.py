"""Settings and test endpoints for Portainer, TrueNAS, Unraid, Node-RED, NPM, Cloudflare, NUT, Speedtest."""
import asyncio
import json
from fastapi import APIRouter, Depends

from ..auth import require_auth
from ..db import get_setting, set_setting
from ..models import (
    CloudflareSettingsIn,
    NodeRedSettingsIn,
    NpmSettingsIn,
    NutSettingsIn,
    PortainerSettingsIn,
    SpeedtestSettingsIn,
    TrueNASSettingsIn,
    UnraidSettingsIn,
)

router = APIRouter()


# ---- Portainer --------------------------------------------------------------

@router.get("/api/portainer-settings")
async def get_portainer_settings(_: bool = Depends(require_auth)):
    return {
        "portainer_url":       get_setting("portainer_url", ""),
        "portainer_token_set": bool(get_setting("portainer_token")),
        "portainer_env_id":    get_setting("portainer_env_id", "1"),
    }


@router.post("/api/portainer-settings")
async def save_portainer_settings(payload: PortainerSettingsIn, _: bool = Depends(require_auth)):
    set_setting("portainer_url",    payload.portainer_url.strip())
    set_setting("portainer_env_id", payload.portainer_env_id.strip() or "1")
    if payload.portainer_token:
        set_setting("portainer_token", payload.portainer_token.strip())
    return {"ok": True}


@router.post("/api/test-portainer")
async def test_portainer(_: bool = Depends(require_auth)):
    from ..portainer import PortainerClient
    url    = get_setting("portainer_url", "")
    token  = get_setting("portainer_token", "")
    env_id = get_setting("portainer_env_id", "1")
    if not (url and token):
        return {"ok": False, "error": "Portainer not configured"}
    client = PortainerClient(url, token, env_id)
    try:
        ok, msg = await client.get_endpoints()
        return {"ok": ok, "error": None if ok else msg}
    finally:
        await client.close()


# ---- TrueNAS ----------------------------------------------------------------

@router.get("/api/truenas-settings")
async def get_truenas_settings(_: bool = Depends(require_auth)):
    return {
        "truenas_url":         get_setting("truenas_url", ""),
        "truenas_api_key_set": bool(get_setting("truenas_api_key")),
    }


@router.post("/api/truenas-settings")
async def save_truenas_settings(payload: TrueNASSettingsIn, _: bool = Depends(require_auth)):
    set_setting("truenas_url", payload.truenas_url.strip())
    if payload.truenas_api_key:
        set_setting("truenas_api_key", payload.truenas_api_key.strip())
    return {"ok": True}


@router.post("/api/test-truenas")
async def test_truenas(_: bool = Depends(require_auth)):
    from ..truenas import TrueNASClient
    url     = get_setting("truenas_url", "")
    api_key = get_setting("truenas_api_key", "")
    if not (url and api_key):
        return {"ok": False, "error": "TrueNAS not configured"}
    client = TrueNASClient(url, api_key)
    try:
        ok, msg = await client.get_system_info()
        return {"ok": ok, "error": None if ok else msg}
    finally:
        await client.close()


# ---- Unraid -----------------------------------------------------------------

@router.get("/api/unraid-settings")
async def get_unraid_settings(_: bool = Depends(require_auth)):
    return {
        "unraid_url":         get_setting("unraid_url", ""),
        "unraid_api_key_set": bool(get_setting("unraid_api_key")),
    }


@router.post("/api/unraid-settings")
async def save_unraid_settings(payload: UnraidSettingsIn, _: bool = Depends(require_auth)):
    set_setting("unraid_url", payload.unraid_url.strip())
    if payload.unraid_api_key:
        set_setting("unraid_api_key", payload.unraid_api_key.strip())
    return {"ok": True}


@router.post("/api/test-unraid")
async def test_unraid(_: bool = Depends(require_auth)):
    from ..unraid import UnraidClient
    url     = get_setting("unraid_url", "")
    api_key = get_setting("unraid_api_key", "")
    if not (url and api_key):
        return {"ok": False, "error": "Unraid not configured"}
    client = UnraidClient(url, api_key)
    try:
        ok, msg = await client.get_info()
        return {"ok": ok, "error": None if ok else msg}
    finally:
        await client.close()


# ---- Node-RED ---------------------------------------------------------------

@router.get("/api/nodered-settings")
async def get_nodered_settings(_: bool = Depends(require_auth)):
    return {
        "nodered_url":          get_setting("nodered_url", ""),
        "nodered_username":     get_setting("nodered_username", ""),
        "nodered_password_set": bool(get_setting("nodered_password")),
    }


@router.post("/api/nodered-settings")
async def save_nodered_settings(payload: NodeRedSettingsIn, _: bool = Depends(require_auth)):
    set_setting("nodered_url",      payload.nodered_url.strip())
    set_setting("nodered_username", payload.nodered_username.strip())
    if payload.nodered_password:
        set_setting("nodered_password", payload.nodered_password)
    return {"ok": True}


@router.post("/api/test-nodered")
async def test_nodered(_: bool = Depends(require_auth)):
    from ..nodered import NodeRedClient
    url  = get_setting("nodered_url", "")
    user = get_setting("nodered_username", "")
    pw   = get_setting("nodered_password", "")
    if not url:
        return {"ok": False, "error": "Node-RED not configured"}
    client = NodeRedClient(url, user, pw or "")
    try:
        ok, msg = await client.get_settings()
        return {"ok": ok, "error": None if ok else msg}
    finally:
        await client.close()


# ---- Nginx Proxy Manager ----------------------------------------------------

@router.get("/api/npm-settings")
async def get_npm_settings(_: bool = Depends(require_auth)):
    return {
        "npm_url":          get_setting("npm_url", ""),
        "npm_username":     get_setting("npm_username", ""),
        "npm_password_set": bool(get_setting("npm_password")),
    }


@router.post("/api/npm-settings")
async def save_npm_settings(payload: NpmSettingsIn, _: bool = Depends(require_auth)):
    set_setting("npm_url",      payload.npm_url.strip())
    set_setting("npm_username", payload.npm_username.strip())
    if payload.npm_password:
        set_setting("npm_password", payload.npm_password)
    return {"ok": True}


@router.post("/api/test-npm")
async def test_npm(_: bool = Depends(require_auth)):
    from ..npm_client import NpmClient
    url  = get_setting("npm_url", "")
    user = get_setting("npm_username", "")
    pw   = get_setting("npm_password", "")
    if not (url and user):
        return {"ok": False, "error": "NPM not configured"}
    client = NpmClient(url, user, pw or "")
    try:
        ok, msg = await client.test()
        return {"ok": ok, "error": None if ok else msg}
    finally:
        await client.close()


# ---- Cloudflare -------------------------------------------------------------

@router.get("/api/cloudflare-settings")
async def get_cloudflare_settings(_: bool = Depends(require_auth)):
    return {
        "cloudflare_api_token_set": bool(get_setting("cloudflare_api_token")),
        "cloudflare_zone_id":       get_setting("cloudflare_zone_id", ""),
    }


@router.post("/api/cloudflare-settings")
async def save_cloudflare_settings(payload: CloudflareSettingsIn, _: bool = Depends(require_auth)):
    set_setting("cloudflare_zone_id", payload.cloudflare_zone_id.strip())
    if payload.cloudflare_api_token:
        set_setting("cloudflare_api_token", payload.cloudflare_api_token.strip())
    return {"ok": True}


@router.post("/api/test-cloudflare")
async def test_cloudflare(_: bool = Depends(require_auth)):
    from ..cloudflare import CloudflareClient
    token   = get_setting("cloudflare_api_token", "")
    zone_id = get_setting("cloudflare_zone_id", "")
    if not (token and zone_id):
        return {"ok": False, "error": "Cloudflare not configured"}
    client = CloudflareClient(token, zone_id)
    try:
        ok, msg = await client.test()
        return {"ok": ok, "error": None if ok else msg}
    finally:
        await client.close()


# ---- NUT / UPS --------------------------------------------------------------

@router.get("/api/nut-settings")
async def get_nut_settings(_: bool = Depends(require_auth)):
    return {
        "nut_host":         get_setting("nut_host", ""),
        "nut_port":         int(get_setting("nut_port", "3493")),
        "nut_ups_name":     get_setting("nut_ups_name", "ups"),
        "nut_username":     get_setting("nut_username", ""),
        "nut_password_set": bool(get_setting("nut_password")),
    }


@router.post("/api/nut-settings")
async def save_nut_settings(payload: NutSettingsIn, _: bool = Depends(require_auth)):
    set_setting("nut_host",     payload.nut_host.strip())
    set_setting("nut_port",     str(payload.nut_port))
    set_setting("nut_ups_name", payload.nut_ups_name.strip() or "ups")
    set_setting("nut_username", payload.nut_username.strip())
    if payload.nut_password:
        set_setting("nut_password", payload.nut_password)
    return {"ok": True}


@router.post("/api/test-nut")
async def test_nut(_: bool = Depends(require_auth)):
    from ..nut import NutClient
    host     = get_setting("nut_host", "")
    port     = int(get_setting("nut_port", "3493"))
    ups_name = get_setting("nut_ups_name", "ups")
    username = get_setting("nut_username", "")
    password = get_setting("nut_password", "")
    if not host:
        return {"ok": False, "error": "NUT not configured"}
    client = NutClient(host, port, ups_name, username, password or "")
    ok, msg = await client.test()
    return {"ok": ok, "error": None if ok else msg}


# ---- Speedtest --------------------------------------------------------------

@router.get("/api/speedtest-settings")
async def get_speedtest_settings(_: bool = Depends(require_auth)):
    return {
        "speedtest_server_id":   get_setting("speedtest_server_id", ""),
        "speedtest_server_name": get_setting("speedtest_server_name", ""),
        "speedtest_source_ip":   get_setting("speedtest_source_ip", ""),
    }


@router.post("/api/speedtest-settings")
async def save_speedtest_settings(payload: SpeedtestSettingsIn, _: bool = Depends(require_auth)):
    set_setting("speedtest_server_id",   payload.speedtest_server_id.strip())
    set_setting("speedtest_server_name", payload.speedtest_server_name.strip())
    set_setting("speedtest_source_ip",   payload.speedtest_source_ip.strip())
    return {"ok": True}


@router.get("/api/speedtest-servers")
async def list_speedtest_servers(_: bool = Depends(require_auth)):
    import math
    import urllib.request
    import speedtest as st_lib
    from ..unifi import UniFiClient
    loop = asyncio.get_running_loop()
    try:
        # Step 1: get primary WAN IP from UniFi
        host    = get_setting("unifi_host", "")
        api_key = get_setting("unifi_api_key", "")
        site    = get_setting("unifi_site", "default")
        primary = get_setting("primary_wan", "wan")
        wan_ip  = ""
        if host and api_key:
            try:
                client = UniFiClient(host, api_key, site)
                wans   = await client.get_gateway_health()
                for w in wans:
                    if w.get("subsystem", "").lower() == primary.lower() and w.get("wan_ip"):
                        wan_ip = w["wan_ip"]
                        break
            except Exception:
                pass

        # Step 2: geolocate primary WAN IP
        geo_url = f"http://ip-api.com/json/{wan_ip}?fields=status,lat,lon,city,country" if wan_ip else "http://ip-api.com/json/?fields=status,lat,lon,city,country"
        geo_raw = await loop.run_in_executor(
            None, lambda: urllib.request.urlopen(geo_url, timeout=10).read().decode()
        )
        geo = json.loads(geo_raw)
        if geo.get("status") == "fail" or geo.get("lat") is None:
            return {"ok": False, "servers": [], "error": f"Could not geolocate {wan_ip}: {geo}"}
        lat, lon = float(geo["lat"]), float(geo["lon"])

        def _haversine(slat, slon):
            R = 6371
            dlat = math.radians(float(slat) - lat)
            dlon = math.radians(float(slon) - lon)
            a = math.sin(dlat/2)**2 + math.cos(math.radians(lat)) * math.cos(math.radians(float(slat))) * math.sin(dlon/2)**2
            return round(R * 2 * math.asin(math.sqrt(a)), 2)

        # Step 3: fetch full server list via speedtest module (has lat/lon per server)
        def _get_servers():
            s = st_lib.Speedtest()
            return s.get_servers()  # {distance: [server_dict, ...]}

        raw = await loop.run_in_executor(None, _get_servers)

        # Step 4: flatten, recalculate distance from primary WAN coords, sort
        servers = []
        for bucket in raw.values():
            for s in bucket:
                try:
                    sid     = str(s.get("id", ""))
                    sponsor = s.get("sponsor", "")
                    name    = s.get("name", "")
                    country = s.get("country", "")
                    slat    = s.get("lat", lat)
                    slon    = s.get("lon", lon)
                    label   = f"{sponsor} ({name}, {country})"
                    servers.append({"id": sid, "label": label, "distance": _haversine(slat, slon)})
                except (ValueError, TypeError):
                    continue

        servers.sort(key=lambda s: s["distance"])
        return {
            "ok": True,
            "servers": servers[:100],
            "geo": {"wan_ip": wan_ip, "city": geo.get("city"), "country": geo.get("country")},
        }
    except Exception as e:
        return {"ok": False, "servers": [], "error": str(e)}
