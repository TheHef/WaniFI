"""Gotify push notification client.

The main dispatch logic lives in notify.py (_send_gotify / send_notification).
This module exposes a standalone helper used by the test endpoint in
routes/notify_channels.py.
"""
import httpx

from .config import log
from .db import get_setting


async def send_gotify(title: str, message: str, priority: int = 5) -> tuple[bool, str]:
    """Send a single Gotify notification. Used by the /api/test-gotify endpoint."""
    url   = get_setting("gotify_url", "")
    token = get_setting("gotify_token", "")
    if not (url and token):
        return False, "Gotify not configured"
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            resp = await client.post(
                f"{url.rstrip('/')}/message",
                headers={"X-Gotify-Key": token},
                json={"title": title, "message": message, "priority": priority},
            )
            resp.raise_for_status()
        return True, "ok"
    except Exception as e:
        log.warning("Gotify notification failed: %s", e)
        return False, str(e)
