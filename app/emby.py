"""Emby Server API client."""
import httpx
from typing import Optional


class EmbyClient:
    def __init__(self, url: str, token: str):
        self.base = url.rstrip("/")
        self.token = token
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10, verify=False)
        return self._client

    def _headers(self) -> dict:
        return {"X-Emby-Token": self.token, "Content-Type": "application/json"}

    async def test(self) -> tuple[bool, str]:
        client = await self._get_client()
        try:
            r = await client.get(f"{self.base}/System/Info", headers=self._headers())
            if r.status_code == 200:
                name = r.json().get("ServerName", "Emby")
                version = r.json().get("Version", "")
                return True, f"Connected to {name} {version}".strip()
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    async def _get_config(self, client: httpx.AsyncClient) -> tuple[bool, dict | str]:
        r = await client.get(f"{self.base}/System/Configuration", headers=self._headers())
        if r.status_code != 200:
            return False, f"Could not read config: HTTP {r.status_code}"
        return True, r.json()

    async def set_bitrate_limit(self, mbps: int) -> tuple[bool, str]:
        """Set remote streaming bitrate limit. mbps=0 means unlimited."""
        client = await self._get_client()
        try:
            ok, result = await self._get_config(client)
            if not ok:
                return False, result
            config = result
            # Emby stores this in bits per second
            config["RemoteClientBitrateLimit"] = mbps * 1_000_000
            r = await client.post(
                f"{self.base}/System/Configuration",
                json=config,
                headers=self._headers(),
            )
            if r.status_code < 400:
                label = f"{mbps} Mbps" if mbps else "unlimited"
                return True, f"Bitrate limit set to {label}"
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    async def clear_bitrate_limit(self) -> tuple[bool, str]:
        return await self.set_bitrate_limit(0)

    async def stop_all_sessions(self) -> tuple[bool, str]:
        client = await self._get_client()
        try:
            r = await client.get(f"{self.base}/Sessions", headers=self._headers())
            if r.status_code != 200:
                return False, f"Could not fetch sessions: HTTP {r.status_code}"
            sessions = [s for s in r.json() if s.get("NowPlayingItem")]
            if not sessions:
                return True, "No active sessions"
            stopped = 0
            for s in sessions:
                sid = s.get("Id", "")
                if not sid:
                    continue
                await client.post(
                    f"{self.base}/Sessions/{sid}/Playing/Stop",
                    headers=self._headers(),
                )
                stopped += 1
            return True, f"Stopped {stopped} session{'s' if stopped != 1 else ''}"
        except Exception as e:
            return False, str(e)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
