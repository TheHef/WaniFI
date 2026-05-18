"""Plex Media Server API client."""
import httpx
from typing import Optional


class PlexClient:
    def __init__(self, url: str, token: str):
        self.base = url.rstrip("/")
        self.token = token
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10, verify=False)
        return self._client

    def _headers(self) -> dict:
        return {
            "X-Plex-Token": self.token,
            "Accept": "application/json",
        }

    async def test(self) -> tuple[bool, str]:
        client = await self._get_client()
        try:
            r = await client.get(f"{self.base}/", headers=self._headers())
            if r.status_code == 200:
                data = r.json()
                name = data.get("MediaContainer", {}).get("friendlyName", "Plex")
                version = data.get("MediaContainer", {}).get("version", "")
                return True, f"Connected to {name} {version}".strip()
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    async def stop_all_streams(self) -> tuple[bool, str]:
        client = await self._get_client()
        try:
            r = await client.get(f"{self.base}/status/sessions", headers=self._headers())
            if r.status_code != 200:
                return False, f"Could not fetch sessions: HTTP {r.status_code}"
            sessions = r.json().get("MediaContainer", {}).get("Metadata", []) or []
            if not sessions:
                return True, "No active streams"
            stopped = 0
            for s in sessions:
                sid = s.get("Session", {}).get("id", "") or s.get("sessionKey", "")
                if not sid:
                    continue
                await client.delete(
                    f"{self.base}/sessions/terminate",
                    params={"sessionId": sid, "reason": "WaniFi failover"},
                    headers=self._headers(),
                )
                stopped += 1
            return True, f"Stopped {stopped} stream{'s' if stopped != 1 else ''}"
        except Exception as e:
            return False, str(e)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
