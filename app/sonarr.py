"""Sonarr v3 API client."""
import httpx
from typing import Optional


class SonarrClient:
    def __init__(self, url: str, api_key: str):
        self.base    = url.rstrip("/")
        self.api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None

    def _headers(self) -> dict:
        return {"X-Api-Key": self.api_key}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15, verify=False)
        return self._client

    async def get_status(self) -> tuple[bool, str]:
        client = await self._get_client()
        try:
            r = await client.get(f"{self.base}/api/v3/system/status", headers=self._headers())
            if r.status_code < 400:
                return True, r.json().get("version", "ok")
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    async def set_indexers_enabled(self, enabled: bool) -> tuple[bool, str]:
        client = await self._get_client()
        try:
            r = await client.get(f"{self.base}/api/v3/indexer", headers=self._headers())
            if r.status_code >= 400:
                return False, f"HTTP {r.status_code}"
            updated = 0
            for indexer in r.json():
                indexer["enableRss"]               = enabled
                indexer["enableAutomaticSearch"]   = enabled
                indexer["enableInteractiveSearch"] = enabled
                resp = await client.put(
                    f"{self.base}/api/v3/indexer/{indexer['id']}",
                    headers=self._headers(), json=indexer,
                )
                if resp.status_code < 400:
                    updated += 1
            return True, f"{updated} indexer(s) {'enabled' if enabled else 'disabled'}"
        except Exception as e:
            return False, str(e)

    async def set_download_clients_enabled(self, enabled: bool) -> tuple[bool, str]:
        client = await self._get_client()
        try:
            r = await client.get(f"{self.base}/api/v3/downloadclient", headers=self._headers())
            if r.status_code >= 400:
                return False, f"HTTP {r.status_code}"
            updated = 0
            for dc in r.json():
                dc["enable"] = enabled
                resp = await client.put(
                    f"{self.base}/api/v3/downloadclient/{dc['id']}",
                    headers=self._headers(), json=dc,
                )
                if resp.status_code < 400:
                    updated += 1
            return True, f"{updated} download client(s) {'enabled' if enabled else 'disabled'}"
        except Exception as e:
            return False, str(e)

    async def search_missing(self) -> tuple[bool, str]:
        client = await self._get_client()
        try:
            r = await client.post(
                f"{self.base}/api/v3/command",
                headers=self._headers(),
                json={"name": "MissingEpisodeSearch"},
            )
            return (r.status_code < 400), ("Missing episode search triggered" if r.status_code < 400 else f"HTTP {r.status_code}")
        except Exception as e:
            return False, str(e)

    async def refresh_all(self) -> tuple[bool, str]:
        client = await self._get_client()
        try:
            r = await client.post(
                f"{self.base}/api/v3/command",
                headers=self._headers(),
                json={"name": "RefreshSeries"},
            )
            return (r.status_code < 400), ("Series refresh triggered" if r.status_code < 400 else f"HTTP {r.status_code}")
        except Exception as e:
            return False, str(e)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
