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
        "speedtest_server_id": get_setting("speedtest_server_id", ""),
        "speedtest_source_ip": get_setting("speedtest_source_ip", ""),
    }


@router.post("/api/speedtest-settings")
async def save_speedtest_settings(payload: SpeedtestSettingsIn, _: bool = Depends(require_auth)):
    set_setting("speedtest_server_id", payload.speedtest_server_id.strip())
    set_setting("speedtest_source_ip", payload.speedtest_source_ip.strip())
    return {"ok": True}


@router.get("/api/speedtest-servers")
async def list_speedtest_servers(wan_ip: str = "", _: bool = Depends(require_auth)):
    import math
    import urllib.request
    loop = asyncio.get_event_loop()
    try:
        # Geolocate the provided WAN IP (or fall back to container's egress IP)
        geo_url = f"http://ip-api.com/json/{wan_ip}?fields=lat,lon,city,country" if wan_ip else "http://ip-api.com/json/?fields=lat,lon,city,country"
        geo_raw = await loop.run_in_executor(
            None,
            lambda: urllib.request.urlopen(geo_url, timeout=10).read().decode(),
        )
        geo = json.loads(geo_raw)
        lat, lon = geo.get("lat"), geo.get("lon")
        if lat is None or lon is None:
            return {"ok": False, "servers": [], "error": "Could not geolocate IP"}

        # Fetch speedtest.net server list by coordinates
        st_url = f"https://www.speedtest.net/api/js/servers?engine=js&limit=100&lat={lat}&lon={lon}&https_functional=true"
        req = urllib.request.Request(st_url, headers={"User-Agent": "Mozilla/5.0"})
        st_raw = await loop.run_in_executor(
            None,
            lambda: urllib.request.urlopen(req, timeout=15).read().decode(),
        )
        st_data = json.loads(st_raw)

        def _dist(slat, slon):
            # Haversine distance in km
            R = 6371
            dlat = math.radians(float(slat) - lat)
            dlon = math.radians(float(slon) - lon)
            a = math.sin(dlat/2)**2 + math.cos(math.radians(lat)) * math.cos(math.radians(float(slat))) * math.sin(dlon/2)**2
            return round(R * 2 * math.asin(math.sqrt(a)), 2)

        servers = []
        for s in st_data:
            sid = str(s.get("id", ""))
            name = s.get("sponsor", s.get("name", ""))
            city = s.get("name", "")
            country = s.get("country", "")
            slat = s.get("lat", lat)
            slon = s.get("lon", lon)
            label = f"{name} ({city}, {country})" if city and city != name else f"{name} ({country})"
            servers.append({"id": sid, "label": label.strip(", "), "distance": _dist(slat, slon)})

        servers.sort(key=lambda s: s["distance"])
        return {"ok": True, "servers": servers, "geo": {"city": geo.get("city"), "country": geo.get("country"), "lat": lat, "lon": lon}}
    except Exception as e:
        return {"ok": False, "servers": [], "error": str(e)}
