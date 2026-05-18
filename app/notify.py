"""Push notification dispatcher — ntfy, Discord, Telegram, Pushover, Gotify."""
import httpx

from .config import NTFY_HTTP_TIMEOUT, log
from .db import get_setting


# ---------------------------------------------------------------------------
# Per-channel helpers
# ---------------------------------------------------------------------------

async def _send_ntfy(title: str, message: str, priority: str, tags: str) -> None:
    url_base = get_setting("ntfy_url", "")
    topic    = get_setting("ntfy_topic", "")
    token    = get_setting("ntfy_token", "")
    if not (url_base and topic):
        return
    url = f"{url_base.rstrip('/')}/{topic}"
    headers: dict = {"Title": title, "Priority": priority}
    if tags:
        headers["Tags"] = tags
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=NTFY_HTTP_TIMEOUT) as client:
            resp = await client.post(url, content=message.encode(), headers=headers)
            resp.raise_for_status()
    except Exception as e:
        log.warning("ntfy notification failed: %s", e)


async def _send_discord(title: str, message: str) -> None:
    webhook_url = get_setting("discord_webhook_url", "")
    if not webhook_url:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json={
                "username": "WaniFi",
                "content": f"**{title}**\n{message}",
            })
            resp.raise_for_status()
    except Exception as e:
        log.warning("Discord notification failed: %s", e)


async def _send_telegram(title: str, message: str) -> None:
    token   = get_setting("telegram_bot_token", "")
    chat_id = get_setting("telegram_chat_id", "")
    if not (token and chat_id):
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": f"*{title}*\n{message}", "parse_mode": "Markdown"},
            )
            resp.raise_for_status()
    except Exception as e:
        log.warning("Telegram notification failed: %s", e)


async def _send_pushover(title: str, message: str) -> None:
    app_token = get_setting("pushover_app_token", "")
    user_key  = get_setting("pushover_user_key", "")
    if not (app_token and user_key):
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.pushover.net/1/messages.json",
                json={"token": app_token, "user": user_key, "title": title, "message": message},
            )
            resp.raise_for_status()
    except Exception as e:
        log.warning("Pushover notification failed: %s", e)


async def _send_gotify(title: str, message: str) -> None:
    gotify_url   = get_setting("gotify_url", "")
    gotify_token = get_setting("gotify_token", "")
    if not (gotify_url and gotify_token):
        return
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            resp = await client.post(
                f"{gotify_url.rstrip('/')}/message",
                headers={"X-Gotify-Key": gotify_token},
                json={"title": title, "message": message, "priority": 5},
            )
            resp.raise_for_status()
    except Exception as e:
        log.warning("Gotify notification failed: %s", e)


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

# Default setting for each event when a channel has no explicit config.
_EVENT_DEFAULTS: dict[str, str] = {
    "failover":     "1",
    "restored":     "1",
    "error":        "0",
    "high_latency": "0",
}


def _channel_wants_event(channel: str, event: str) -> bool:
    """Return True if the channel has opted in to this event type.

    If *event* is empty (legacy / test call) we always send.
    Channels without per-event settings (Discord, Telegram, Pushover) always
    send when the integration toggle is on.
    """
    if not event:
        return True
    key     = f"{channel}_on_{event}"
    default = _EVENT_DEFAULTS.get(event, "1")
    return get_setting(key, default) == "1"


async def send_notification(
    title: str,
    message: str,
    priority: str = "default",
    tags: str = "",
    event: str = "",
) -> tuple[bool, str]:
    """Dispatch to all enabled notification channels.

    *event* — one of 'failover', 'restored', 'error', 'high_latency'.
    Each channel checks its own per-event opt-in settings.
    Channels without per-event settings (Discord, Telegram, Pushover) always
    fire when their integration toggle is enabled.
    Returns (False, error_msg) only when ntfy is the sole failing channel
    (preserved for backwards-compat with the test endpoint).
    """
    errors: list[str] = []

    if get_setting("integration_ntfy", "0") == "1" and _channel_wants_event("ntfy", event):
        url_base = get_setting("ntfy_url", "")
        topic    = get_setting("ntfy_topic", "")
        token    = get_setting("ntfy_token", "")
        if url_base and topic:
            url = f"{url_base.rstrip('/')}/{topic}"
            headers: dict = {"Title": title, "Priority": priority}
            if tags:
                headers["Tags"] = tags
            if token:
                headers["Authorization"] = f"Bearer {token}"
            try:
                async with httpx.AsyncClient(timeout=NTFY_HTTP_TIMEOUT) as client:
                    resp = await client.post(url, content=message.encode(), headers=headers)
                    resp.raise_for_status()
            except Exception as e:
                log.warning("ntfy notification failed: %s", e)
                errors.append(str(e))

    if get_setting("integration_discord", "0") == "1":
        await _send_discord(title, message)

    if get_setting("integration_telegram", "0") == "1":
        await _send_telegram(title, message)

    if get_setting("integration_pushover", "0") == "1":
        await _send_pushover(title, message)

    if get_setting("integration_gotify", "0") == "1" and _channel_wants_event("gotify", event):
        await _send_gotify(title, message)

    return (False, errors[0]) if errors else (True, "ok")


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

async def test_ntfy() -> tuple[bool, str]:
    """Test ntfy specifically (for the test endpoint)."""
    url_base = get_setting("ntfy_url", "")
    topic    = get_setting("ntfy_topic", "")
    token    = get_setting("ntfy_token", "")
    if not (url_base and topic):
        return False, "ntfy not configured"
    url = f"{url_base.rstrip('/')}/{topic}"
    headers: dict = {"Title": "WaniFi Test", "Priority": "default"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=NTFY_HTTP_TIMEOUT) as client:
            resp = await client.post(url, content=b"Test notification from WaniFi", headers=headers)
            resp.raise_for_status()
        return True, "ok"
    except Exception as e:
        return False, str(e)


async def test_discord() -> tuple[bool, str]:
    webhook_url = get_setting("discord_webhook_url", "")
    if not webhook_url:
        return False, "Discord not configured"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json={
                "username": "WaniFi",
                "content": "**WaniFi Test**\nDiscord notifications are working.",
            })
            resp.raise_for_status()
        return True, "ok"
    except Exception as e:
        return False, str(e)


async def test_telegram() -> tuple[bool, str]:
    token   = get_setting("telegram_bot_token", "")
    chat_id = get_setting("telegram_chat_id", "")
    if not (token and chat_id):
        return False, "Telegram not configured"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": "*WaniFi Test*\nTelegram notifications are working.", "parse_mode": "Markdown"},
            )
            resp.raise_for_status()
        return True, "ok"
    except Exception as e:
        return False, str(e)


async def test_pushover() -> tuple[bool, str]:
    app_token = get_setting("pushover_app_token", "")
    user_key  = get_setting("pushover_user_key", "")
    if not (app_token and user_key):
        return False, "Pushover not configured"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.pushover.net/1/messages.json",
                json={"token": app_token, "user": user_key, "title": "WaniFi Test", "message": "Pushover notifications are working."},
            )
            resp.raise_for_status()
        return True, "ok"
    except Exception as e:
        return False, str(e)
