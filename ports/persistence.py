"""
Persistence port for Phase 1 canonical content APIs and Phase 2 collections/search helpers.
"""
from typing import Optional, Protocol

from domain.models import Collection, ContentItem, ExtractionJob, ExtractedMenuItem, Location


class PersistencePort(Protocol):
    async def create_content(self, owner_user_id: str, source_url: str) -> ContentItem:
        ...

    async def get_content(self, content_id: str, owner_user_id: str) -> Optional[ContentItem]:
        ...

    async def list_feed(self, owner_user_id: str, limit: int, offset: int) -> list[ContentItem]:
        ...

    async def create_extraction_job(self, content_id: str) -> ExtractionJob:
        ...

    async def get_latest_job_by_content(self, content_id: str) -> Optional[ExtractionJob]:
        ...

    async def get_content_by_id(self, content_id: str) -> Optional[ContentItem]:
        """Internal/worker lookup by primary key (no owner filter)."""

    async def list_active_extractions(self, owner_user_id: str, *, limit: int = 50) -> list[ContentItem]:
        """Content items for this user that are not in a terminal state (feed-style cards)."""

    async def get_extraction_job_by_id(self, job_id: str) -> Optional[ExtractionJob]:
        ...

    async def admin_force_requeue_job(self, job_id: str) -> bool:
        """Reset a job stuck in `processing` back to `queued`. Returns False if job missing."""

    async def cancel_extraction_for_user(self, owner_user_id: str, content_id: str) -> bool:
        """Cancel in-flight extraction for owned content (queued/processing)."""

    async def list_stuck_extraction_job_ids(self, *, older_than_minutes: int, limit: int = 200) -> list[str]:
        """Jobs stuck in ``processing`` (server died mid-request) for backfill / ops."""

    async def update_content(
        self,
        content_id: str,
        owner_user_id: str,
        *,
        status: str | None = None,
        title_original: str | None = None,
        title_generated: str | None = None,
        summary_text: str | None = None,
        summary_method: str | None = None,
        thumbnail_url: str | None = None,
        likes_count: int | None = None,
        comments_count: int | None = None,
        views_count: int | None = None,
        semantic_tags: list[str] | None = None,
        mood_tags: list[str] | None = None,
        curator_insight: str | None = None,
        summary_prompt_json: dict | None = None,
        model_response_json: dict | None = None,
    ) -> Optional[ContentItem]:
        ...

    async def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        progress_percent: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        attempt: int | None = None,
        next_retry_at_iso: str | None = None,
        clear_next_retry_at: bool = False,
        clear_error_fields: bool = False,
    ) -> Optional[ExtractionJob]:
        ...

    async def delete_content(self, content_id: str, owner_user_id: str) -> bool:
        """Delete content and all associated data (locations, jobs, menu items). Returns False if not found."""

    async def upsert_locations(self, content_id: str, locations: list[Location]) -> None:
        ...

    async def list_map_locations(self, owner_user_id: str) -> list[Location]:
        ...

    async def list_locations_for_content(self, content_id: str, owner_user_id: str) -> list[Location]:
        ...

    async def add_bookmark(self, owner_user_id: str, content_id: str) -> None:
        ...

    async def list_bookmark_content_ids(self, owner_user_id: str) -> list[str]:
        ...


    async def upsert_menu_items(
        self, content_id: str, owner_user_id: str, items: list[ExtractedMenuItem]
    ) -> None:
        ...

    async def list_menu_items(self, content_id: str, owner_user_id: str) -> list[ExtractedMenuItem]:
        ...

    async def search_content(
        self,
        owner_user_id: str,
        *,
        q: str | None = None,
        smart: str | None = None,
        max_results: int = 500,
    ) -> list[ContentItem]:
        ...

    async def list_collections(self, owner_user_id: str, limit: int, offset: int) -> list[Collection]:
        ...

    async def create_collection(
        self,
        owner_user_id: str,
        name: str,
        description: str | None,
        collection_type: str,
        cover_image_url: str | None,
    ) -> Collection:
        ...

    async def get_collection(self, collection_id: str, owner_user_id: str) -> Optional[Collection]:
        ...

    async def update_collection(
        self,
        collection_id: str,
        owner_user_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        cover_image_url: str | None = None,
    ) -> Optional[Collection]:
        ...

    async def delete_collection(self, collection_id: str, owner_user_id: str) -> bool:
        ...

    async def add_collection_item(self, collection_id: str, owner_user_id: str, content_id: str) -> None:
        ...

    async def remove_collection_item(self, collection_id: str, owner_user_id: str, content_id: str) -> None:
        ...

    async def list_collection_items(
        self, collection_id: str, owner_user_id: str, limit: int, offset: int
    ) -> list[ContentItem]:
        ...
