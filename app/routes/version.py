"""Version check — compares running build SHA against latest GitHub commit."""
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends

from ..auth import require_auth

router = APIRouter(prefix="/api/version")

_VERSION_FILE = Path(__file__).parent.parent / "VERSION"
_GH_API_URL   = "https://api.github.com/repos/TheHef/WaniFi/commits/main"
_CACHE_TTL    = 3600

_cache: dict = {"ts": 0.0, "latest_sha": None}


def _read_current_sha() -> str:
    try:
        return _VERSION_FILE.read_text().strip()
    except Exception:
        return "dev"


@router.get("")
async def get_version(_=Depends(require_auth)):
    now = time.monotonic()
    if now - _cache["ts"] > _CACHE_TTL:
        try:
            async with httpx.AsyncClient(
                timeout=10,
                headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
            ) as client:
                r = await client.get(_GH_API_URL)
                _cache["latest_sha"] = r.json().get("sha", "")
        except Exception:
            pass
        _cache["ts"] = now

    current = _read_current_sha()
    latest  = _cache["latest_sha"] or ""
    up_to_date = (
        current == "dev"
        or not latest
        or current == latest
        or latest.startswith(current)
        or current.startswith(latest[:7])
    )
    return {
        "current":    current[:7] if len(current) > 7 else current,
        "latest":     latest[:7]  if len(latest)  > 7 else latest,
        "up_to_date": up_to_date,
    }
