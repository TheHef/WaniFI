"""System routes: status, live stats, metrics, UniFi diagnostics, health check."""
import json
import time

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..auth import require_auth
from ..config import APP_VERSION
from ..db import db, get_setting, get_state
from ..docker_ops import docker_ok
from ..unifi import UniFiClient
from ..watcher import state

router = APIRouter()


@router.get("/api/status")
async def api_status(_: bool = Depends(require_auth)):
    return {
        "active_wan":         state.current_wan,
        "last_check":         state.last_check,
        "last_error":         state.last_error,
        "state_changed_at":   state.state_changed_at,
        "configured":         bool(get_setting("unifi_host") and get_setting("unifi_api_key")),
        "docker_ok":          docker_ok(),
        "primary_wan":        get_setting("primary_wan", "wan"),
        "failover_wan":       get_setting("failover_wan", "wan2"),
        "primary_wan_name":   get_setting("primary_wan_name", ""),
        "failover_wan_name":  get_setting("failover_wan_name", ""),
        "raw_wans":           json.loads(get_state("last_wans") or "[]"),
        "gateway_info":       json.loads(get_state("gateway_info") or "{}"),
        "version":            APP_VERSION,
    }


@router.get("/api/live")
async def api_live(_: bool = Depends(require_auth)):
    return state.live_gw_info


@router.get("/api/metrics")
async def api_metrics(range: str = "1h", _: bool = Depends(require_auth)):
    range_map = {
        "1h":  (3600,        0),
        "12h": (43_200,    300),
        "1d":  (86_400,    900),
        "7d":  (604_800,  3_600),
        "30d": (2_592_000, 14_400),
    }
    if range not in range_map:
        range = "1h"
    seconds, bucket = range_map[range]
    since = int(time.time()) - seconds

    with db() as conn:
        if bucket == 0:
            rows = conn.execute(
                "SELECT ts, rx_mbps, tx_mbps, latency_ms FROM wan_metrics "
                "WHERE ts >= ? ORDER BY ts",
                (since,),
            ).fetchall()
            labels = [r["ts"] * 1000 for r in rows]
        else:
            rows = conn.execute(
                """
                SELECT (ts / ?) * ? AS bucket,
                       AVG(rx_mbps)   AS rx_mbps,
                       AVG(tx_mbps)   AS tx_mbps,
                       AVG(latency_ms) AS latency_ms
                  FROM wan_metrics
                 WHERE ts >= ?
                 GROUP BY bucket ORDER BY bucket
                """,
                (bucket, bucket, since),
            ).fetchall()
            labels = [int(r["bucket"]) * 1000 for r in rows]

    def _round(v, n):
        return round(v, n) if v is not None else None

    return {
        "labels":  labels,
        "rx":      [_round(r["rx_mbps"], 2)    for r in rows],
        "tx":      [_round(r["tx_mbps"], 2)    for r in rows],
        "latency": [_round(r["latency_ms"], 1) for r in rows],
    }


@router.post("/api/test-unifi")
async def api_test_unifi(_: bool = Depends(require_auth)):
    host    = get_setting("unifi_host")
    api_key = get_setting("unifi_api_key")
    site    = get_setting("unifi_site", "default")
    if not (host and api_key):
        return JSONResponse({"ok": False, "error": "Missing UniFi host or API key"}, status_code=400)

    client = UniFiClient(host, api_key, site)
    try:
        wans    = await client.get_gateway_health()
        gw_info = await client.get_gateway_info()
        active  = gw_info.get("active_wan", "").upper()

        discovered: list[dict] = []
        for w in wans:
            name = w.get("subsystem", "")
            discovered.append({
                "subsystem": name,
                "status":    w.get("status"),
                "wan_ip":    w.get("wan_ip"),
                "isp_name":  w.get("isp_name") or w.get("isp_organization"),
                "active":    active == name.upper(),
            })
            for uname, us in (w.get("uptime_stats") or {}).items():
                if not any(d["subsystem"].upper() == uname.upper() for d in discovered):
                    discovered.append({
                        "subsystem": uname.lower(),
                        "status":    "ok" if us.get("availability", 0) > 0 else "unknown",
                        "wan_ip":    None,
                        "isp_name":  None,
                        "active":    active == uname.upper(),
                    })

        # Annotate with device that provides each WAN: native ports first, then extras in order
        native = {"wan", "wan2"}
        extras = gw_info.get("extra_devices", [])
        idx = 0
        for entry in discovered:
            if entry["subsystem"].lower() in native:
                entry["device_model"] = gw_info.get("gw_model", "")
                entry["device_name"]  = gw_info.get("gw_name",  "")
            else:
                if idx < len(extras):
                    entry["device_model"] = extras[idx].get("model", "")
                    entry["device_name"]  = extras[idx].get("name",  "")
                    idx += 1
                else:
                    entry["device_model"] = ""
                    entry["device_name"]  = ""

        sites = await client.get_sites()
        return {
            "ok": True,
            "wans": wans,
            "discovered_wans": discovered,
            "active_wan": gw_info.get("active_wan", ""),
            "sites": sites,
        }
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        await client.close()


@router.get("/api/debug-wan")
async def api_debug_wan(_: bool = Depends(require_auth)):
    host    = get_setting("unifi_host")
    api_key = get_setting("unifi_api_key")
    site    = get_setting("unifi_site", "default")
    if not (host and api_key):
        return JSONResponse({"ok": False, "error": "Missing UniFi host or API key"}, status_code=400)
    client = UniFiClient(host, api_key, site)
    try:
        health = await client._get(f"/proxy/network/api/s/{client.site}/stat/health")
        device = await client._get(f"/proxy/network/api/s/{client.site}/stat/device")
        return {
            "health_all_subsystems": health.get("data", []),
            "devices": device.get("data", []),
        }
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        await client.close()


@router.get("/api/probe-cellular")
async def api_probe_cellular(_: bool = Depends(require_auth)):
    """Try several UniFi endpoints to locate cellular signal data."""
    host    = get_setting("unifi_host")
    api_key = get_setting("unifi_api_key")
    site    = get_setting("unifi_site", "default")
    if not (host and api_key):
        return JSONResponse({"ok": False, "error": "Missing UniFi host or API key"}, status_code=400)
    client = UniFiClient(host, api_key, site)

    candidates = [
        # v1 integration API (newer UniFi OS)
        "/proxy/network/integration/v1/sites",
        "/proxy/network/api/v1/sites",
        "/proxy/network/integration/v1/sites/{site}/devices",
        "/proxy/network/api/v1/sites/{site}/devices",
        # Widget variants
        "/proxy/network/api/s/{site}/stat/widget/lte",
        "/proxy/network/api/s/{site}/stat/widget/wan",
        "/proxy/network/api/s/{site}/stat/widget/health",
        # Device manager commands
        "/proxy/network/api/s/{site}/cmd/devmgr",
        # Per-device stats
        "/proxy/network/api/s/{site}/stat/devicedetail",
        # Original from previous probe (keep for completeness)
        "/proxy/network/api/s/{site}/stat/widget/cellular",
    ]

    results: dict = {}
    try:
        # Resolve the v1 site UUID
        sites_v1 = await client._get("/proxy/network/integration/v1/sites")
        site_uuid = next((s.get("id") for s in sites_v1.get("data", [])
                          if s.get("internalReference") == client.site or s.get("name", "").lower() == "default"), None)
        results["site_uuid"] = site_uuid

        device_data = await client._get(f"/proxy/network/api/s/{client.site}/stat/device")
        umbb = next((d for d in device_data.get("data", [])
                     if d.get("type", "").lower() == "umbb"
                     or "UMBB" in d.get("model", "")
                     or "U5G" in (d.get("name", "") or "")), None)
        results["found_device"] = {
            "name": umbb.get("name") if umbb else None,
            "model": umbb.get("model") if umbb else None,
            "mac": umbb.get("mac") if umbb else None,
            "_id": umbb.get("_id") if umbb else None,
        } if umbb else None

        if site_uuid:
            # Fetch all v1 devices, find U5G Max by MAC
            devices_v1 = await client._get(
                f"/proxy/network/integration/v1/sites/{site_uuid}/devices?limit=100"
            )
            umbb_v1 = next((d for d in devices_v1.get("data", [])
                            if umbb and d.get("macAddress", "").lower() == umbb.get("mac", "").lower()), None)
            results["v1_device"] = umbb_v1

            if umbb_v1:
                v1_uuid = umbb_v1.get("id", "")
                for path in (
                    f"/proxy/network/integration/v1/sites/{site_uuid}/devices/{v1_uuid}",
                    f"/proxy/network/integration/v1/sites/{site_uuid}/devices/{v1_uuid}/statistics",
                    f"/proxy/network/integration/v1/sites/{site_uuid}/devices/{v1_uuid}/interfaces",
                    f"/proxy/network/integration/v1/sites/{site_uuid}/devices/{v1_uuid}/interfaces/wan",
                    f"/proxy/network/integration/v1/sites/{site_uuid}/devices/{v1_uuid}/cellular",
                ):
                    try:
                        r = await client.client.get(path)
                        results[path] = {
                            "status": r.status_code,
                            "size": len(r.content),
                            "snippet": r.text[:2000] if r.status_code < 400 else r.text[:200],
                        }
                    except Exception as e:
                        results[path] = {"error": str(e)}
        return results
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        await client.close()


@router.get("/healthz")
async def healthz():
    return {"ok": True, "version": APP_VERSION}
