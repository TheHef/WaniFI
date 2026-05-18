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
        "sonarr": f"Sonarr: {payload.action}",
        "radarr": f"Radarr: {payload.action}",
        "webhook": payload.command.strip(),
    }
    return labels.get(t) or payload.command.strip()


@router.get("")
async def list_rules(_: bool = Depends(require_auth)):
    with db() as conn:
        rules = [dict(r) for r in conn.execute("SELECT * FROM rules ORDER BY id").fetchall()]
    return {"rules": rules}


@router.post("")
async def create_rule(payload: RuleIn, _: bool = Depends(require_auth)):
    _validate(payload)
    name = _default_name(payload)
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO rules(rule_type,name,container,trigger,action,command,enabled,delay_seconds) "
            "VALUES(?,?,?,?,?,?,?,?)",
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
