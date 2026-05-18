"""Deluge Web UI JSON-RPC client."""
import httpx
from typing import Any, Optional


class DelugeClient:
    def __init__(self, url: str, password: str):
        self.base     = url.rstrip("/")
        self.password = password
        self._client: Optional[httpx.AsyncClient] = None
        self._cookies: dict = {}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10, verify=False)
        return self._client

    async def _call(self, method: str, params: Optional[list] = None) -> tuple[bool, Any]:
        client = await self._get_client()
        try:
            r = await client.post(
                f"{self.base}/json",
                json={"method": method, "params": params or [], "id": 1},
                cookies=self._cookies,
                headers={"Content-Type": "application/json"},
            )
            if r.status_code < 400:
                data = r.json()
                if data.get("error"):
                    return False, data["error"].get("message", "error")
                return True, data.get("result")
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    async def login(self) -> tuple[bool, str]:
        client = await self._get_client()
        try:
            r = await client.post(
                f"{self.base}/json",
                json={"method": "auth.login", "params": [self.password], "id": 1},
                headers={"Content-Type": "application/json"},
            )
            if r.status_code < 400:
                self._cookies = dict(r.cookies)
                data = r.json()
                if data.get("result") is True:
                    return True, "ok"
                return False, "Invalid password"
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    async def pause_all(self) -> tuple[bool, str]:
        ok, result = await self._call("core.pause_all_torrents")
        return ok, "All torrents paused" if ok else str(result)

    async def resume_all(self) -> tuple[bool, str]:
        ok, result = await self._call("core.resume_all_torrents")
        return ok, "All torrents resumed" if ok else str(result)

    async def set_dl_limit(self, down_kbps: int) -> tuple[bool, str]:
        ok, result = await self._call("core.set_config", [{"max_download_speed": down_kbps}])
        label = f"{down_kbps} KB/s" if down_kbps > 0 else "unlimited"
        return ok, f"Download limit set to {label}" if ok else str(result)

    async def set_ul_limit(self, up_kbps: int) -> tuple[bool, str]:
        ok, result = await self._call("core.set_config", [{"max_upload_speed": up_kbps}])
        label = f"{up_kbps} KB/s" if up_kbps > 0 else "unlimited"
        return ok, f"Upload limit set to {label}" if ok else str(result)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
