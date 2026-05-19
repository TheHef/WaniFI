"""Nginx Proxy Manager API client."""
import httpx
from typing import Optional


class NpmClient:
    def __init__(self, url: str, username: str, password: str):
        self.base     = url.rstrip("/")
        self.username = username
        self.password = password
        self._token: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15, verify=False)
        return self._client

    async def _auth(self) -> bool:
        client = await self._get_client()
        try:
            r = await client.post(
                f"{self.base}/api/tokens",
                json={"identity": self.username, "secret": self.password},
            )
            if r.status_code == 200:
                self._token = r.json().get("token", "")
                return bool(self._token)
            return False
        except Exception:
            return False

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    async def test(self) -> tuple[bool, str]:
        if not await self._auth():
            return False, "Authentication failed — check credentials"
        client = await self._get_client()
        try:
            r = await client.get(f"{self.base}/api/nginx/proxy-hosts", headers=self._headers())
            if r.status_code == 200:
                count = len(r.json())
                return True, f"Connected — {count} proxy host{'s' if count != 1 else ''}"
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    async def _find_host(self, client: httpx.AsyncClient, name: str) -> Optional[dict]:
        """Find proxy host by domain name or numeric ID."""
        r = await client.get(f"{self.base}/api/nginx/proxy-hosts", headers=self._headers())
        if r.status_code != 200:
            return None
        hosts = r.json()
        # Try numeric ID first
        if name.isdigit():
            iid = int(name)
            return next((h for h in hosts if h.get("id") == iid), None)
        # Match by first domain_name in domain_names list
        return next(
            (h for h in hosts if name in (h.get("domain_names") or [])),
            None,
        )

    async def set_host_enabled(self, name: str, enabled: bool) -> tuple[bool, str]:
        if not await self._auth():
            return False, "Authentication failed"
        client = await self._get_client()
        try:
            host = await self._find_host(client, name)
            if not host:
                return False, f"Proxy host '{name}' not found"
            hid = host.get("id")
            # NPM requires the full object for PUT
            host["enabled"] = 1 if enabled else 0
            r = await client.put(
                f"{self.base}/api/nginx/proxy-hosts/{hid}",
                json=host,
                headers=self._headers(),
            )
            if r.status_code < 400:
                state = "enabled" if enabled else "disabled"
                domains = ", ".join(host.get("domain_names", [str(hid)]))
                return True, f"Proxy host '{domains}' {state}"
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
