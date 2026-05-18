"""Portainer API client."""
import httpx
from typing import Optional


class PortainerClient:
    def __init__(self, url: str, token: str, env_id: str = "1"):
        self.base   = url.rstrip("/")
        self.token  = token
        self.env_id = env_id or "1"
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=10, verify=False,
                headers={"X-API-Key": self.token},
            )
        return self._client

    async def get_endpoints(self) -> tuple[bool, str]:
        client = await self._get_client()
        try:
            r = await client.get(f"{self.base}/api/endpoints")
            if r.status_code < 400:
                return True, "ok"
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    async def container_action(self, container_name: str, action: str) -> tuple[bool, str]:
        """Start, stop, or restart a named container."""
        client = await self._get_client()
        try:
            r = await client.get(
                f"{self.base}/api/endpoints/{self.env_id}/docker/containers/json",
                params={"all": "true"},
            )
            if r.status_code >= 400:
                return False, f"HTTP {r.status_code}"
            containers = r.json()
            container_id = None
            for c in containers:
                names = c.get("Names", [])
                if any(n.strip("/") == container_name for n in names):
                    container_id = c["Id"]
                    break
            if not container_id:
                return False, f"Container '{container_name}' not found"
            r2 = await client.post(
                f"{self.base}/api/endpoints/{self.env_id}/docker/containers/{container_id}/{action}"
            )
            # 204 = success, 304 = already in desired state (also success)
            if r2.status_code < 400:
                return True, f"Container '{container_name}' {action}ed"
            return False, f"HTTP {r2.status_code}"
        except Exception as e:
            return False, str(e)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
