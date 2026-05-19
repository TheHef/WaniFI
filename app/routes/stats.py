"""Failover statistics and speedtest endpoints."""
import asyncio

from fastapi import APIRouter, Depends

from ..auth import require_auth
from ..db import db, a_log_event

router = APIRouter()


@router.get("/api/stats")
async def get_stats(_: bool = Depends(require_auth)):
    with db() as conn:
        rows = conn.execute(
            """SELECT ts, message FROM events
               WHERE message LIKE '%-> failover%'
                  OR message LIKE '%-> primary%'
                  OR message LIKE '%-> down%'
               ORDER BY ts DESC LIMIT 50"""
        ).fetchall()

    events = [{"type": _classify(r["message"]), "ts": r["ts"]} for r in rows]
    failovers = [e for e in events if e["type"] == "failover"]

    last_failover  = failovers[0]["ts"] if failovers else None
    restored_events = [e for e in events if e["type"] == "restored"]
    last_restored  = restored_events[0]["ts"] if restored_events else None

    from ..speedtest_runner import get_last_speedtest
    return {
        "total_failovers":  len(failovers),
        "last_failover":    last_failover,
        "last_restored":    last_restored,
        "recent_events":    events[:10],
        "last_speedtest":   get_last_speedtest(),
    }


@router.post("/api/run-speedtest")
async def run_speedtest_now(_: bool = Depends(require_auth)):
    from ..speedtest_runner import run_speedtest, get_last_speedtest
    ok, msg = await run_speedtest()
    await a_log_event("info" if ok else "error", f"Manual speedtest: {msg}")
    result = get_last_speedtest() if ok else None
    return {"ok": ok, "msg": msg, "result": result}


@router.get("/api/speedtest-running")
async def speedtest_running_status(_: bool = Depends(require_auth)):
    from ..speedtest_runner import _running
    return {"running": _running}


def _classify(message: str) -> str:
    if "-> failover" in message:
        return "failover"
    if "-> primary" in message:
        return "restored"
    return "down"
