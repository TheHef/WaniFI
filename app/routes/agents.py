"""Agent registration, management, and WebSocket hub endpoint."""
import secrets

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..agent_hub import deliver_response, is_online, online_keys, register, send_command, unregister
from ..auth import require_auth
from ..db import create_agent, delete_agent, get_agent_by_key, list_agents

router = APIRouter(prefix="/api/agents")


class AgentIn(BaseModel):
    name: str


# ---------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------

@router.get("")
async def get_agents(_=Depends(require_auth)):
    agents = list_agents()
    keys = online_keys()
    for a in agents:
        a["online"] = a["api_key"] in keys
    return agents


@router.post("")
async def add_agent(body: AgentIn, _=Depends(require_auth)):
    if not body.name.strip():
        raise HTTPException(400, "Name required")
    api_key = secrets.token_hex(32)
    agent = create_agent(body.name.strip(), api_key)
    agent["online"] = False
    return agent


@router.delete("/{agent_id}")
async def remove_agent(agent_id: int, _=Depends(require_auth)):
    # Find the key so we can check online status
    agents = list_agents()
    target = next((a for a in agents if a["id"] == agent_id), None)
    if not target:
        raise HTTPException(404, "Agent not found")
    delete_agent(agent_id)
    return {"ok": True}


@router.get("/{agent_id}/containers")
async def get_agent_containers(agent_id: int, _=Depends(require_auth)):
    agents = list_agents()
    target = next((a for a in agents if a["id"] == agent_id), None)
    if not target:
        raise HTTPException(404, "Agent not found")
    result = await send_command(target["api_key"], {"type": "list_containers"})
    if not result or not result.get("ok"):
        raise HTTPException(502, result.get("error", "Agent unreachable") if result else "Agent unreachable")
    return result["containers"]


@router.post("/{agent_id}/ping")
async def ping_agent(agent_id: int, _=Depends(require_auth)):
    agents = list_agents()
    target = next((a for a in agents if a["id"] == agent_id), None)
    if not target:
        raise HTTPException(404, "Agent not found")
    result = await send_command(target["api_key"], {"type": "ping"})
    return result


# ---------------------------------------------------------------------------
# WebSocket — agents connect here
# ---------------------------------------------------------------------------

@router.websocket("/ws")
async def agent_ws(ws: WebSocket):
    import asyncio, json as _json
    await ws.accept()
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=10)
        msg = _json.loads(raw)
    except Exception:
        await ws.close(code=4400)
        return

    if msg.get("type") != "auth":
        await ws.send_text(_json.dumps({"ok": False, "error": "expected auth"}))
        await ws.close(code=4400)
        return

    agent = get_agent_by_key(msg.get("key", ""))
    if not agent:
        await ws.send_text(_json.dumps({"ok": False, "error": "invalid key"}))
        await ws.close(code=4401)
        return

    api_key = agent["api_key"]
    await ws.send_text(_json.dumps({"ok": True}))
    register(api_key, agent["name"], ws)
    try:
        while True:
            data = await ws.receive_text()
            deliver_response(api_key, data)
    except WebSocketDisconnect:
        pass
    finally:
        unregister(api_key)
