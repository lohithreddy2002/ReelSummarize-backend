"""
In-memory storage for local dev/tests (StoragePort).
"""
from ports.storage import StoragePort


class InMemoryStorageAdapter(StoragePort):
    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}
        self._types: dict[str, str] = {}

    async def put_object(self, path: str, data: bytes, content_type: str) -> str:
        self._blobs[path] = data
        self._types[path] = content_type
        return path

    async def get_signed_url(self, path: str, ttl_seconds: int) -> str:
        _ = ttl_seconds
        return f"memory://{path}"

    async def delete_object(self, path: str) -> None:
        self._blobs.pop(path, None)
        self._types.pop(path, None)
