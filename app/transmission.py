"""Transmission RPC client."""
import httpx
from typing import Optional


class TransmissionClient:
    def __init__(self, url: str, username: str, password: str):
        self.rpc_url  = url.rstrip("/").rstrip("/transmission/rpc") + "/transmission/rpc"
        self.username = username
        self.password = password
        self._session_id: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            auth = httpx.BasicAuth(self.username, self.password) if self.username else None
            self._client = httpx.AsyncClient(timeout=10, verify=False, auth=auth)
        return self._client

    async def _rpc(self, method: str, arguments: Optional[dict] = None) -> tuple[bool, dict]:
        client = await self._get_client()
        payload = {"method": method, "arguments": arguments or {}}
        headers = {}
        if self._session_id:
            headers["X-Transmission-Session-Id"] = self._session_id
        try:
            r = await client.post(self.rpc_url, json=payload, headers=headers)
            if r.status_code == 409:
                self._session_id = r.headers.get("X-Transmission-Session-Id", "")
                headers["X-Transmission-Session-Id"] = self._session_id
                r = await client.post(self.rpc_url, json=payload, headers=headers)
            if r.status_code < 400:
                data = r.json()
                ok = data.get("result") == "success"
                return ok, data
            return False, {"result": f"HTTP {r.status_code}"}
        except Exception as e:
            return False, {"result": str(e)}

    async def get_session(self) -> tuple[bool, str]:
        ok, data = await self._rpc("session-get")
        return ok, data.get("result", "error")

    async def pause_all(self) -> tuple[bool, str]:
        ok, data = await self._rpc("torrent-stop")
        return ok, "All torrents stopped" if ok else data.get("result", "error")

    async def resume_all(self) -> tuple[bool, str]:
        ok, data = await self._rpc("torrent-start")
        return ok, "All torrents started" if ok else data.get("result", "error")

    async def set_alt_speed(self, enabled: bool) -> tuple[bool, str]:
        ok, data = await self._rpc("session-set", {"alt-speed-enabled": enabled})
        label = "enabled" if enabled else "disabled"
        return ok, f"Alt speed {label}" if ok else data.get("result", "error")

    async def set_dl_limit(self, down_kbps: int) -> tuple[bool, str]:
        args = {"speed-limit-down": down_kbps, "speed-limit-down-enabled": down_kbps > 0}
        ok, data = await self._rpc("session-set", args)
        label = f"{down_kbps} KB/s" if down_kbps > 0 else "unlimited"
        return ok, f"Download limit set to {label}" if ok else data.get("result", "error")

    async def set_ul_limit(self, up_kbps: int) -> tuple[bool, str]:
        args = {"speed-limit-up": up_kbps, "speed-limit-up-enabled": up_kbps > 0}
        ok, data = await self._rpc("session-set", args)
        label = f"{up_kbps} KB/s" if up_kbps > 0 else "unlimited"
        return ok, f"Upload limit set to {label}" if ok else data.get("result", "error")

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
