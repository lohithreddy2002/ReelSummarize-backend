"""
Supabase Storage REST adapter (StoragePort).
"""
from typing import Any

import httpx

from ports.storage import StoragePort


class SupabaseStorageAdapter(StoragePort):
    def __init__(self, project_url: str, secret_key: str, bucket: str) -> None:
        self._base = f"{project_url.rstrip('/')}/storage/v1"
        self._headers = {
            "apikey": secret_key,
            "Authorization": f"Bearer {secret_key}",
        }
        self._bucket = bucket

    async def put_object(self, path: str, data: bytes, content_type: str) -> str:
        safe_path = path.lstrip("/")
        url = f"{self._base}/object/{self._bucket}/{safe_path}"
        headers = {**self._headers, "Content-Type": content_type, "x-upsert": "true"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, content=data)
        response.raise_for_status()
        return path

    async def get_signed_url(self, path: str, ttl_seconds: int) -> str:
        safe_path = path.lstrip("/")
        url = f"{self._base}/object/sign/{self._bucket}/{safe_path}"
        payload: dict[str, Any] = {"expiresIn": ttl_seconds}
        headers = {**self._headers, "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        signed = data.get("signedURL") or data.get("signedUrl")
        if not signed:
            raise RuntimeError("Supabase storage sign response missing signed URL")
        if signed.startswith("http"):
            return signed
        return f"{self._base.replace('/storage/v1', '')}{signed}"

    async def delete_object(self, path: str) -> None:
        safe_path = path.lstrip("/")
        url = f"{self._base}/object/{self._bucket}/{safe_path}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.delete(url, headers=self._headers)
        if response.status_code not in (200, 204):
            response.raise_for_status()
