"""
Phase 2 collections API service.
"""
from domain.models import Collection, ContentItem
from ports.persistence import PersistencePort


class CollectionsService:
    def __init__(self, persistence: PersistencePort) -> None:
        self._p = persistence

    async def list_collections(self, owner_user_id: str, limit: int, offset: int) -> list[Collection]:
        return await self._p.list_collections(owner_user_id, limit, offset)

    async def create_collection(
        self,
        owner_user_id: str,
        name: str,
        description: str | None,
        collection_type: str,
        cover_image_url: str | None,
    ) -> Collection:
        return await self._p.create_collection(
            owner_user_id, name, description, collection_type, cover_image_url
        )

    async def update_collection(
        self,
        owner_user_id: str,
        collection_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        cover_image_url: str | None = None,
    ) -> Collection | None:
        return await self._p.update_collection(collection_id, owner_user_id, name=name, description=description, cover_image_url=cover_image_url)

    async def delete_collection(self, owner_user_id: str, collection_id: str) -> bool:
        return await self._p.delete_collection(collection_id, owner_user_id)

    async def add_item(self, owner_user_id: str, collection_id: str, content_id: str) -> None:
        await self._p.add_collection_item(collection_id, owner_user_id, content_id)

    async def remove_item(self, owner_user_id: str, collection_id: str, content_id: str) -> None:
        await self._p.remove_collection_item(collection_id, owner_user_id, content_id)

    async def list_items(
        self, owner_user_id: str, collection_id: str, limit: int, offset: int
    ) -> list[ContentItem]:
        return await self._p.list_collection_items(collection_id, owner_user_id, limit, offset)
