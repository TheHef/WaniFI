"""Cloudflare API client."""
import httpx
from typing import Optional


class CloudflareClient:
    BASE = "https://api.cloudflare.com/client/v4"

    def __init__(self, api_token: str, zone_id: str):
        self.api_token = api_token
        self.zone_id   = zone_id
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15)
        return self._client

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_token}", "Content-Type": "application/json"}

    async def test(self) -> tuple[bool, str]:
        client = await self._get_client()
        try:
            r = await client.get(
                f"{self.BASE}/zones/{self.zone_id}",
                headers=self._headers(),
            )
            if r.status_code == 200:
                name = r.json().get("result", {}).get("name", self.zone_id)
                return True, f"Connected — zone: {name}"
            errors = r.json().get("errors", [])
            msg = errors[0].get("message", f"HTTP {r.status_code}") if errors else f"HTTP {r.status_code}"
            return False, msg
        except Exception as e:
            return False, str(e)

    async def set_security_level(self, level: str) -> tuple[bool, str]:
        """Set zone security level.
        Valid: off, essentially_off, low, medium, high, under_attack
        """
        client = await self._get_client()
        try:
            r = await client.patch(
                f"{self.BASE}/zones/{self.zone_id}/settings/security_level",
                json={"value": level},
                headers=self._headers(),
            )
            if r.status_code == 200:
                return True, f"Security level set to '{level}'"
            errors = r.json().get("errors", [])
            msg = errors[0].get("message", f"HTTP {r.status_code}") if errors else f"HTTP {r.status_code}"
            return False, msg
        except Exception as e:
            return False, str(e)

    async def enable_under_attack(self) -> tuple[bool, str]:
        return await self.set_security_level("under_attack")

    async def disable_under_attack(self) -> tuple[bool, str]:
        return await self.set_security_level("medium")

    async def purge_cache(self) -> tuple[bool, str]:
        client = await self._get_client()
        try:
            r = await client.post(
                f"{self.BASE}/zones/{self.zone_id}/purge_cache",
                json={"purge_everything": True},
                headers=self._headers(),
            )
            if r.status_code == 200:
                return True, "Cache purged for zone"
            errors = r.json().get("errors", [])
            msg = errors[0].get("message", f"HTTP {r.status_code}") if errors else f"HTTP {r.status_code}"
            return False, msg
        except Exception as e:
            return False, str(e)

    async def set_development_mode(self, enabled: bool) -> tuple[bool, str]:
        """Toggle development mode (bypasses cache for 3 hours)."""
        client = await self._get_client()
        try:
            r = await client.patch(
                f"{self.BASE}/zones/{self.zone_id}/settings/development_mode",
                json={"value": "on" if enabled else "off"},
                headers=self._headers(),
            )
            if r.status_code == 200:
                state = "enabled" if enabled else "disabled"
                return True, f"Development mode {state}"
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
