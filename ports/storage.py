"""
Storage port abstraction.
"""
from typing import Protocol


class StoragePort(Protocol):
    async def put_object(self, path: str, data: bytes, content_type: str) -> str:
        ...

    async def get_signed_url(self, path: str, ttl_seconds: int) -> str:
        ...

    async def delete_object(self, path: str) -> None:
        ...
