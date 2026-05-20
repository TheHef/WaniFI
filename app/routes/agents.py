"""Agent registration, management, and WebSocket hub endpoint."""
import secrets

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..agent_hub import is_online, online_keys, register, send_command, unregister
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
async def agent_ws(ws: WebSocket, key: str = ""):
    api_key = key or ws.headers.get("x-agent-key", "")
    agent = get_agent_by_key(api_key)
    if not agent:
        await ws.close(code=4401)
        return

    await ws.accept()
    register(api_key, agent["name"], ws)
    try:
        while True:
            # Keep connection alive; actual command/response flow is driven
            # by send_command() calls from rules execution
            data = await ws.receive_text()
            # Responses to commands are handled inside send_command() via
            # receive_text() — any unsolicited messages are ignored here
    except WebSocketDisconnect:
        pass
    finally:
        unregister(api_key)
