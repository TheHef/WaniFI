"""qBittorrent WebUI API v2 client."""
import httpx
from typing import Optional


class QBittorrentClient:
    def __init__(self, url: str, username: str, password: str):
        self.base = url.rstrip("/")
        self.username = username
        self.password = password
        self._client: Optional[httpx.AsyncClient] = None
        self._sid: Optional[str] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10, verify=False)
        return self._client

    async def login(self) -> tuple[bool, str]:
        client = await self._get_client()
        try:
            r = await client.post(
                f"{self.base}/api/v2/auth/login",
                data={"username": self.username, "password": self.password},
            )
            if r.text.strip() == "Ok.":
                self._sid = r.cookies.get("SID")
                return True, "ok"
            return False, "Invalid credentials"
        except Exception as e:
            return False, str(e)

    def _cookies(self) -> dict:
        return {"SID": self._sid} if self._sid else {}

    async def _post(self, path: str, data: Optional[dict] = None) -> tuple[bool, str]:
        client = await self._get_client()
        try:
            r = await client.post(
                f"{self.base}{path}", data=data or {}, cookies=self._cookies()
            )
            if r.status_code == 403:
                ok, err = await self.login()
                if not ok:
                    return False, f"Auth failed: {err}"
                r = await client.post(
                    f"{self.base}{path}", data=data or {}, cookies=self._cookies()
                )
            return r.status_code < 400, r.text.strip() or "ok"
        except Exception as e:
            return False, str(e)

    async def _get_speed_mode(self) -> int:
        client = await self._get_client()
        try:
            r = await client.get(
                f"{self.base}/api/v2/transfer/speedLimitsMode", cookies=self._cookies()
            )
            return int(r.text.strip())
        except Exception:
            return -1

    async def set_alt_speed(self, enable: bool) -> tuple[bool, str]:
        current = await self._get_speed_mode()
        if current == -1:
            return False, "Could not read speed mode"
        if (current == 1) == enable:
            return True, "already set"
        return await self._post("/api/v2/transfer/toggleSpeedLimitsMode")

    async def set_download_limit(self, kbps: int) -> tuple[bool, str]:
        return await self._post(
            "/api/v2/transfer/setDownloadLimit", {"limit": str(kbps * 1024)}
        )

    async def set_upload_limit(self, kbps: int) -> tuple[bool, str]:
        return await self._post(
            "/api/v2/transfer/setUploadLimit", {"limit": str(kbps * 1024)}
        )

    async def pause_all(self) -> tuple[bool, str]:
        ok, msg = await self._post("/api/v2/torrents/pause", {"hashes": "all"})
        if not ok:
            ok, msg = await self._post("/api/v2/torrents/stopAll")
        return ok, msg

    async def resume_all(self) -> tuple[bool, str]:
        ok, msg = await self._post("/api/v2/torrents/resume", {"hashes": "all"})
        if not ok:
            ok, msg = await self._post("/api/v2/torrents/startAll")
        return ok, msg

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
