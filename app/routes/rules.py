"""Automation rules CRUD."""
from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_auth
from ..db import db, log_event
from ..models import (
    RuleIn,
    VALID_ACTIONS,
    VALID_TRIGGERS,
    VALID_QB_ACTIONS,
    VALID_SABNZBD_ACTIONS,
    VALID_TRANSMISSION_ACTIONS,
    VALID_DELUGE_ACTIONS,
    VALID_EMBY_ACTIONS,
    VALID_JELLYFIN_ACTIONS,
    VALID_PLEX_ACTIONS,
    VALID_HA_ACTIONS,
    VALID_PROXMOX_ACTIONS,
    VALID_SONARR_ACTIONS,
    VALID_RADARR_ACTIONS,
    VALID_WEBHOOK_ACTIONS,
    VALID_PIHOLE_ACTIONS,
    VALID_ADGUARD_ACTIONS,
    VALID_PORTAINER_ACTIONS,
    VALID_TRUENAS_ACTIONS,
    VALID_UNRAID_ACTIONS,
    VALID_NODERED_ACTIONS,
    VALID_NZBGET_ACTIONS,
    VALID_UNIFI_RULE_ACTIONS,
    VALID_SPEEDTEST_ACTIONS,
    VALID_NPM_ACTIONS,
    VALID_CLOUDFLARE_ACTIONS,
    VALID_NUT_ACTIONS,
)
from ..watcher import (
    execute_host_command,
    run_qb_action,
    run_sabnzbd_action,
    run_transmission_action,
    run_deluge_action,
    run_emby_action,
    run_jellyfin_action,
    run_plex_action,
    run_ha_action,
    run_proxmox_action,
    run_sonarr_action,
    run_radarr_action,
    run_webhook_action,
    run_pihole_action,
    run_adguard_action,
    run_portainer_action,
    run_truenas_action,
    run_unraid_action,
    run_nodered_action,
    run_nzbget_action,
    run_unifi_rule_action,
    run_speedtest_action,
    run_npm_action,
    run_cloudflare_action,
    run_nut_action,
)
from ..docker_ops import container_action

router = APIRouter(prefix="/api/rules")


def _validate(payload: RuleIn):
    if payload.trigger not in VALID_TRIGGERS:
        raise HTTPException(400, f"trigger must be one of {VALID_TRIGGERS}")
    t = payload.rule_type
    if t == "docker":
        if payload.action not in VALID_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_ACTIONS}")
        if not payload.container.strip():
            raise HTTPException(400, "container required for docker rules")
    elif t == "host_command":
        if not payload.command.strip():
            raise HTTPException(400, "command required for host_command rules")
    elif t == "qbittorrent":
        if payload.action not in VALID_QB_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_QB_ACTIONS}")
    elif t == "sabnzbd":
        if payload.action not in VALID_SABNZBD_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_SABNZBD_ACTIONS}")
    elif t == "transmission":
        if payload.action not in VALID_TRANSMISSION_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_TRANSMISSION_ACTIONS}")
    elif t == "deluge":
        if payload.action not in VALID_DELUGE_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_DELUGE_ACTIONS}")
    elif t == "emby":
        if payload.action not in VALID_EMBY_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_EMBY_ACTIONS}")
    elif t == "jellyfin":
        if payload.action not in VALID_JELLYFIN_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_JELLYFIN_ACTIONS}")
    elif t == "plex":
        if payload.action not in VALID_PLEX_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_PLEX_ACTIONS}")
    elif t == "homeassistant":
        if payload.action not in VALID_HA_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_HA_ACTIONS}")
    elif t == "proxmox":
        if payload.action not in VALID_PROXMOX_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_PROXMOX_ACTIONS}")
        if not payload.container.strip():
            raise HTTPException(400, "node/vmid required for proxmox rules")
    elif t == "sonarr":
        if payload.action not in VALID_SONARR_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_SONARR_ACTIONS}")
    elif t == "radarr":
        if payload.action not in VALID_RADARR_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_RADARR_ACTIONS}")
    elif t == "webhook":
        if not payload.command.strip():
            raise HTTPException(400, "URL required for webhook rules")
    elif t == "pihole":
        if payload.action not in VALID_PIHOLE_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_PIHOLE_ACTIONS}")
    elif t == "adguard":
        if payload.action not in VALID_ADGUARD_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_ADGUARD_ACTIONS}")
    elif t == "portainer":
        if payload.action not in VALID_PORTAINER_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_PORTAINER_ACTIONS}")
        if not payload.container.strip():
            raise HTTPException(400, "container name required for portainer rules")
    elif t == "truenas":
        if payload.action not in VALID_TRUENAS_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_TRUENAS_ACTIONS}")
        if not payload.container.strip():
            raise HTTPException(400, "service name required for truenas rules")
    elif t == "unraid":
        if payload.action not in VALID_UNRAID_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_UNRAID_ACTIONS}")
        if not payload.container.strip():
            raise HTTPException(400, "VM name required for unraid rules")
    elif t == "nodered":
        if payload.action not in VALID_NODERED_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_NODERED_ACTIONS}")
        if not payload.command.strip():
            raise HTTPException(400, "flow endpoint required for nodered rules")
    elif t == "nzbget":
        if payload.action not in VALID_NZBGET_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_NZBGET_ACTIONS}")
    elif t == "unifi_rule":
        if payload.action not in VALID_UNIFI_RULE_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_UNIFI_RULE_ACTIONS}")
        if payload.action in ("disable_wlan", "enable_wlan", "block_client", "unblock_client") and not payload.container.strip():
            raise HTTPException(400, "container (WLAN name / MAC) required for this action")
    elif t == "speedtest":
        if payload.action not in VALID_SPEEDTEST_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_SPEEDTEST_ACTIONS}")
    elif t == "npm":
        if payload.action not in VALID_NPM_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_NPM_ACTIONS}")
        if not payload.container.strip():
            raise HTTPException(400, "Proxy host name or ID required")
    elif t == "cloudflare":
        if payload.action not in VALID_CLOUDFLARE_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_CLOUDFLARE_ACTIONS}")
    elif t == "nut":
        if payload.action not in VALID_NUT_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_NUT_ACTIONS}")
    else:
        raise HTTPException(400, f"Unknown rule_type: {t!r}")


def _default_name(payload: RuleIn) -> str:
    name = payload.name.strip()
    if name:
        return name
    t = payload.rule_type
    labels = {
        "docker": payload.container,
        "qbittorrent": f"qB: {payload.action}",
        "sabnzbd": f"SABnzbd: {payload.action}",
        "transmission": f"Transmission: {payload.action}",
        "deluge": f"Deluge: {payload.action}",
        "emby": f"Emby: {payload.action}",
        "jellyfin": f"Jellyfin: {payload.action}",
        "plex": f"Plex: {payload.action}",
        "homeassistant": f"HA: {payload.action}",
        "proxmox": f"Proxmox: {payload.container} {payload.action}",
        "sonarr":    f"Sonarr: {payload.action}",
        "radarr":    f"Radarr: {payload.action}",
        "webhook":   payload.command.strip(),
        "pihole":    f"Pi-hole: {payload.action}",
        "adguard":   f"AdGuard: {payload.action}",
        "portainer": f"Portainer: {payload.container} {payload.action}",
        "truenas":   f"TrueNAS: {payload.container} {payload.action}",
        "unraid":    f"Unraid: {payload.container} {payload.action}",
        "nodered":   f"Node-RED: {payload.command}",
        "nzbget":    f"NZBGet: {payload.action}",
    }
    return labels.get(t) or payload.command.strip()


@router.get("")
async def list_rules(_: bool = Depends(require_auth)):
    with db() as conn:
        rules = [dict(r) for r in conn.execute(
            "SELECT * FROM rules ORDER BY sort_order, id"
        ).fetchall()]
    return {"rules": rules}


@router.post("/reorder")
async def reorder_rules(payload: dict, _: bool = Depends(require_auth)):
    ids = payload.get("ids", [])
    if not ids:
        return {"ok": True}
    with db() as conn:
        for order, rule_id in enumerate(ids):
            conn.execute("UPDATE rules SET sort_order=? WHERE id=?", (order, rule_id))
    return {"ok": True}


@router.post("")
async def create_rule(payload: RuleIn, _: bool = Depends(require_auth)):
    _validate(payload)
    name = _default_name(payload)
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO rules(rule_type,name,container,trigger,action,command,enabled,delay_seconds,sort_order) "
            "VALUES(?,?,?,?,?,?,?,?,(SELECT COALESCE(MAX(sort_order),0)+1 FROM rules))",
            (payload.rule_type, name, payload.container.strip(), payload.trigger,
             payload.action, payload.command.strip(), 1 if payload.enabled else 0,
             max(0, payload.delay_seconds)),
        )
    log_event("info", f"Rule created ({payload.rule_type}) on {payload.trigger}: {name}")
    return {"ok": True, "id": cur.lastrowid}


@router.patch("/{rule_id}")
async def update_rule(rule_id: int, payload: RuleIn, _: bool = Depends(require_auth)):
    _validate(payload)
    name = _default_name(payload)
    with db() as conn:
        if not conn.execute("SELECT 1 FROM rules WHERE id=?", (rule_id,)).fetchone():
            raise HTTPException(404)
        conn.execute(
            "UPDATE rules SET rule_type=?,name=?,container=?,trigger=?,action=?,command=?,delay_seconds=? "
            "WHERE id=?",
            (payload.rule_type, name, payload.container.strip(), payload.trigger,
             payload.action, payload.command.strip(),
             max(0, payload.delay_seconds), rule_id),
        )
    log_event("info", f"Rule {rule_id} updated")
    return {"ok": True}


@router.delete("/{rule_id}")
async def delete_rule(rule_id: int, _: bool = Depends(require_auth)):
    with db() as conn:
        conn.execute("DELETE FROM rules WHERE id=?", (rule_id,))
    log_event("info", f"Rule {rule_id} deleted")
    return {"ok": True}


@router.post("/{rule_id}/run")
async def run_rule(rule_id: int, _: bool = Depends(require_auth)):
    with db() as conn:
        row = conn.execute("SELECT * FROM rules WHERE id=?", (rule_id,)).fetchone()
        if not row:
            raise HTTPException(404)
    rule = dict(row)
    t = rule["rule_type"]
    action = rule["action"]
    value  = rule["container"] or ""

    if t == "host_command":
        ok, msg = await execute_host_command(rule["command"])
    elif t == "qbittorrent":
        ok, msg = await run_qb_action(action, value)
    elif t == "sabnzbd":
        ok, msg = await run_sabnzbd_action(action, value)
    elif t == "transmission":
        ok, msg = await run_transmission_action(action, value)
    elif t == "deluge":
        ok, msg = await run_deluge_action(action, value)
    elif t == "emby":
        ok, msg = await run_emby_action(action, value)
    elif t == "jellyfin":
        ok, msg = await run_jellyfin_action(action, value)
    elif t == "plex":
        ok, msg = await run_plex_action(action, value)
    elif t == "homeassistant":
        ok, msg = await run_ha_action(action, value)
    elif t == "proxmox":
        ok, msg = await run_proxmox_action(action, value)
    elif t == "sonarr":
        ok, msg = await run_sonarr_action(action)
    elif t == "radarr":
        ok, msg = await run_radarr_action(action)
    elif t == "webhook":
        ok, msg = await run_webhook_action(rule["command"], value or "POST")
    elif t == "pihole":
        ok, msg = await run_pihole_action(action)
    elif t == "adguard":
        ok, msg = await run_adguard_action(action)
    elif t == "portainer":
        ok, msg = await run_portainer_action(action, value)
    elif t == "truenas":
        ok, msg = await run_truenas_action(action, value)
    elif t == "unraid":
        ok, msg = await run_unraid_action(action, value)
    elif t == "nodered":
        ok, msg = await run_nodered_action(action, rule["command"])
    elif t == "nzbget":
        ok, msg = await run_nzbget_action(action, value)
    elif t == "unifi_rule":
        ok, msg = await run_unifi_rule_action(action, value)
    elif t == "speedtest":
        ok, msg = await run_speedtest_action()
    elif t == "npm":
        ok, msg = await run_npm_action(action, value)
    elif t == "cloudflare":
        ok, msg = await run_cloudflare_action(action)
    elif t == "nut":
        ok, msg = await run_nut_action(action)
    else:
        ok, msg = container_action(rule["container"], action)

    log_event("info" if ok else "error", f"Rule '{rule['name']}' run manually: {msg}")
    return {"ok": ok, "message": msg}


@router.post("/{rule_id}/toggle")
async def toggle_rule(rule_id: int, _: bool = Depends(require_auth)):
    with db() as conn:
        row = conn.execute("SELECT enabled FROM rules WHERE id=?", (rule_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        new_val = 0 if row["enabled"] else 1
        conn.execute("UPDATE rules SET enabled=? WHERE id=?", (new_val, rule_id))
    return {"ok": True, "enabled": bool(new_val)}
