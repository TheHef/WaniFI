"""Pi-hole API client (supports v5 and v6)."""
import httpx
from typing import Optional


class PiholeClient:
    def __init__(self, url: str, token: str):
        self.base  = url.rstrip("/")
        self.token = token
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10, verify=False)
        return self._client

    async def _auth_v6(self) -> Optional[str]:
        """Authenticate against Pi-hole v6 REST API.
        POSTs the stored token/password and returns a session SID, or None."""
        if not self.token:
            return None
        client = await self._get_client()
        try:
            r = await client.post(
                f"{self.base}/api/auth",
                json={"password": self.token},
            )
            if r.status_code < 400:
                sid = r.json().get("session", {}).get("sid")
                return sid or None
        except Exception:
            pass
        return None

    async def _delete_session_v6(self, sid: str) -> None:
        """Log out / delete a Pi-hole v6 session."""
        client = await self._get_client()
        try:
            await client.delete(
                f"{self.base}/api/auth",
                headers={"X-FTL-SID": sid},
            )
        except Exception:
            pass

    async def get_summary(self) -> tuple[bool, str]:
        client = await self._get_client()
        # Try v6 first
        sid = await self._auth_v6()
        if sid:
            try:
                r = await client.get(
                    f"{self.base}/api/stats/summary",
                    headers={"X-FTL-SID": sid},
                )
                await self._delete_session_v6(sid)
                if r.status_code < 400:
                    return True, "Pi-hole v6 connected"
            except Exception:
                pass
        # Fallback to v5
        try:
            r = await client.get(
                f"{self.base}/admin/api.php",
                params={"auth": self.token, "summaryRaw": ""},
            )
            if r.status_code < 400:
                return True, "Pi-hole v5 connected"
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    async def enable(self) -> tuple[bool, str]:
        client = await self._get_client()
        # Try v6
        sid = await self._auth_v6()
        if sid:
            try:
                r = await client.post(
                    f"{self.base}/api/dns/blocking",
                    json={"blocking": True, "timer": None},
                    headers={"X-FTL-SID": sid},
                )
                await self._delete_session_v6(sid)
                if r.status_code < 400:
                    return True, "Pi-hole blocking enabled (v6)"
            except Exception:
                pass
        # Fallback to v5
        try:
            r = await client.get(
                f"{self.base}/admin/api.php",
                params={"auth": self.token, "enable": ""},
            )
            if r.status_code < 400:
                return True, "Pi-hole enabled"
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    async def disable(self) -> tuple[bool, str]:
        client = await self._get_client()
        # Try v6
        sid = await self._auth_v6()
        if sid:
            try:
                r = await client.post(
                    f"{self.base}/api/dns/blocking",
                    json={"blocking": False, "timer": None},
                    headers={"X-FTL-SID": sid},
                )
                await self._delete_session_v6(sid)
                if r.status_code < 400:
                    return True, "Pi-hole blocking disabled (v6)"
            except Exception:
                pass
        # Fallback to v5
        try:
            r = await client.get(
                f"{self.base}/admin/api.php",
                params={"auth": self.token, "disable": ""},
            )
            if r.status_code < 400:
                return True, "Pi-hole disabled"
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
