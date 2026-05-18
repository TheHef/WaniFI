"""NZBGet JSON-RPC API client."""
import httpx
from typing import Optional


class NZBGetClient:
    def __init__(self, url: str, username: str = "", password: str = ""):
        self.base     = url.rstrip("/")
        self.username = username
        self.password = password
        self._client: Optional[httpx.AsyncClient] = None
        self._req_id  = 0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            auth = (self.username, self.password) if self.username else None
            self._client = httpx.AsyncClient(timeout=10, verify=False, auth=auth)
        return self._client

    async def _call(self, method: str, params: list = None) -> tuple[bool, any]:
        client = await self._get_client()
        self._req_id += 1
        try:
            r = await client.post(
                f"{self.base}/jsonrpc",
                json={"version": "1.1", "id": self._req_id, "method": method, "params": params or []},
            )
            if r.status_code >= 400:
                return False, f"HTTP {r.status_code}"
            data = r.json()
            if data.get("error"):
                return False, data["error"].get("message", "RPC error")
            return True, data.get("result")
        except Exception as e:
            return False, str(e)

    async def get_version(self) -> tuple[bool, str]:
        ok, result = await self._call("version")
        return ok, str(result) if ok else str(result)

    async def pause(self) -> tuple[bool, str]:
        ok, r = await self._call("pausedownload")
        return ok, "Download paused" if ok else str(r)

    async def resume(self) -> tuple[bool, str]:
        ok, r = await self._call("resumedownload")
        return ok, "Download resumed" if ok else str(r)

    async def set_speed_limit(self, limit_kb: int) -> tuple[bool, str]:
        try:
            limit_kb = int(limit_kb)
        except (ValueError, TypeError):
            limit_kb = 0
        ok, r = await self._call("rate", [limit_kb])
        return ok, f"Speed limit set to {limit_kb} KB/s" if ok else str(r)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
