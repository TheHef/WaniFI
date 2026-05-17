"""Automation rules CRUD."""
from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_auth
from ..db import db, log_event
from ..models import RuleIn, VALID_ACTIONS, VALID_TRIGGERS

VALID_QB_ACTIONS = ("alt_speed_on", "alt_speed_off", "set_dl_limit", "set_ul_limit", "pause_all", "resume_all")

router = APIRouter(prefix="/api/rules")


def _validate(payload: RuleIn):
    if payload.trigger not in VALID_TRIGGERS:
        raise HTTPException(400, f"trigger must be one of {VALID_TRIGGERS}")
    if payload.rule_type == "docker":
        if payload.action not in VALID_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_ACTIONS}")
        if not payload.container.strip():
            raise HTTPException(400, "container required for docker rules")
    elif payload.rule_type == "host_command":
        if not payload.command.strip():
            raise HTTPException(400, "command required for host_command rules")
    elif payload.rule_type == "qbittorrent":
        if payload.action not in VALID_QB_ACTIONS:
            raise HTTPException(400, f"action must be one of {VALID_QB_ACTIONS}")
    else:
        raise HTTPException(400, "rule_type must be 'docker', 'host_command', or 'qbittorrent'")


def _default_name(payload: RuleIn) -> str:
    name = payload.name.strip()
    if name:
        return name
    if payload.rule_type == "docker":
        return payload.container
    if payload.rule_type == "qbittorrent":
        return f"qB: {payload.action}"
    return payload.command.strip()


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
            "INSERT INTO rules(rule_type,name,container,trigger,action,command,enabled) "
            "VALUES(?,?,?,?,?,?,?)",
            (payload.rule_type, name, payload.container.strip(), payload.trigger,
             payload.action, payload.command.strip(), 1 if payload.enabled else 0),
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
            "UPDATE rules SET rule_type=?,name=?,container=?,trigger=?,action=?,command=? "
            "WHERE id=?",
            (payload.rule_type, name, payload.container.strip(), payload.trigger,
             payload.action, payload.command.strip(), rule_id),
        )
    log_event("info", f"Rule {rule_id} updated")
    return {"ok": True}


@router.delete("/{rule_id}")
async def delete_rule(rule_id: int, _: bool = Depends(require_auth)):
    with db() as conn:
        conn.execute("DELETE FROM rules WHERE id=?", (rule_id,))
    log_event("info", f"Rule {rule_id} deleted")
    return {"ok": True}


@router.post("/{rule_id}/toggle")
async def toggle_rule(rule_id: int, _: bool = Depends(require_auth)):
    with db() as conn:
        row = conn.execute("SELECT enabled FROM rules WHERE id=?", (rule_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        new_val = 0 if row["enabled"] else 1
        conn.execute("UPDATE rules SET enabled=? WHERE id=?", (new_val, rule_id))
    return {"ok": True, "enabled": bool(new_val)}
