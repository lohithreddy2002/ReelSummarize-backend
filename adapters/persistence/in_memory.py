"""
In-memory persistence adapter used as default local Phase 1 store.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from domain.models import Collection, ContentItem, ExtractionJob, ExtractedMenuItem, Location
from ports.persistence import PersistencePort


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _norm_q(q: str | None) -> str:
    return (q or "").strip().lower()


class InMemoryPersistenceAdapter(PersistencePort):
    def __init__(self) -> None:
        self._content: dict[str, ContentItem] = {}
        self._jobs: dict[str, ExtractionJob] = {}
        self._locations_by_content: dict[str, list[Location]] = {}
        self._bookmarks: set[tuple[str, str]] = set()
        self._collections: dict[str, Collection] = {}
        self._collection_items: dict[str, list[str]] = {}
        self._menu_items: dict[str, list[ExtractedMenuItem]] = {}

    async def create_content(self, owner_user_id: str, source_url: str) -> ContentItem:
        platform = "instagram" if "instagram.com" in source_url else "unknown"
        item = ContentItem(
            owner_user_id=owner_user_id,
            source_url=source_url,
            source_platform=platform,
            source_type="reel",
            status="queued",
        )
        self._content[item.id] = item
        return replace(item)

    async def get_content(self, content_id: str, owner_user_id: str) -> ContentItem | None:
        item = self._content.get(content_id)
        if not item or item.owner_user_id != owner_user_id:
            return None
        return replace(item)

    async def delete_content(self, content_id: str, owner_user_id: str) -> bool:
        item = self._content.get(content_id)
        if not item or item.owner_user_id != owner_user_id:
            return False
        del self._content[content_id]
        self._locations_by_content.pop(content_id, None)
        self._menu_items.pop(content_id, None)
        self._jobs = {k: v for k, v in self._jobs.items() if v.content_id != content_id}
        return True

    async def list_feed(self, owner_user_id: str, limit: int, offset: int) -> list[ContentItem]:
        rows = [c for c in self._content.values() if c.owner_user_id == owner_user_id]
        rows.sort(key=lambda x: x.created_at, reverse=True)
        return [replace(x) for x in rows[offset : offset + limit]]

    async def create_extraction_job(self, content_id: str) -> ExtractionJob:
        job = ExtractionJob(content_id=content_id, status="queued", stage="queued", progress_percent=0)
        self._jobs[job.id] = job
        return replace(job)

    async def get_latest_job_by_content(self, content_id: str) -> ExtractionJob | None:
        jobs = [j for j in self._jobs.values() if j.content_id == content_id]
        if not jobs:
            return None
        jobs.sort(key=lambda x: x.created_at, reverse=True)
        return replace(jobs[0])

    async def get_content_by_id(self, content_id: str) -> ContentItem | None:
        item = self._content.get(content_id)
        return replace(item) if item else None

    async def list_active_extractions(self, owner_user_id: str, *, limit: int = 50) -> list[ContentItem]:
        rows = [c for c in self._content.values() if c.owner_user_id == owner_user_id and c.status in ("queued", "processing")]
        rows.sort(key=lambda x: x.created_at, reverse=True)
        return [replace(x) for x in rows[:limit]]

    async def get_extraction_job_by_id(self, job_id: str) -> ExtractionJob | None:
        job = self._jobs.get(job_id)
        return replace(job) if job else None

    async def admin_force_requeue_job(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        job.status = "queued"
        job.stage = "queued"
        job.progress_percent = 0
        job.attempt = 0
        job.locked_until = None
        job.next_retry_at = None
        job.error_code = None
        job.error_message = None
        job.updated_at = _utcnow()
        content = self._content.get(job.content_id)
        if content:
            content.status = "queued"
            content.updated_at = _utcnow()
        return True

    async def cancel_extraction_for_user(self, owner_user_id: str, content_id: str) -> bool:
        content = self._content.get(content_id)
        if not content or content.owner_user_id != owner_user_id:
            return False
        if content.status not in ("queued", "processing"):
            return False
        job = await self.get_latest_job_by_content(content_id)
        if job and job.status not in ("completed", "dead_letter"):
            j = self._jobs.get(job.id)
            if j:
                j.status = "failed"
                j.stage = "cancelled"
                j.progress_percent = 100
                j.error_code = "USER_CANCELLED"
                j.error_message = "Cancelled by user"
                j.locked_until = None
                j.updated_at = _utcnow()
        content.status = "error"
        content.updated_at = _utcnow()
        return True

    async def list_stuck_extraction_job_ids(self, *, older_than_minutes: int, limit: int = 200) -> list[str]:
        cutoff = _utcnow() - timedelta(minutes=older_than_minutes)
        stuck = [j.id for j in self._jobs.values() if j.status == "processing" and j.updated_at < cutoff]
        return stuck[:limit]

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
    ) -> ContentItem | None:
        item = self._content.get(content_id)
        if not item or item.owner_user_id != owner_user_id:
            return None
        if status is not None:
            item.status = status
        if title_original is not None:
            item.title_original = title_original
        if title_generated is not None:
            item.title_generated = title_generated
        if summary_text is not None:
            item.summary_text = summary_text
        if summary_method is not None:
            item.summary_method = summary_method
        if thumbnail_url is not None:
            item.thumbnail_url = thumbnail_url
        if likes_count is not None:
            item.likes_count = likes_count
        if comments_count is not None:
            item.comments_count = comments_count
        if views_count is not None:
            item.views_count = views_count
        if semantic_tags is not None:
            item.semantic_tags = semantic_tags
        if mood_tags is not None:
            item.mood_tags = mood_tags
        if curator_insight is not None:
            item.curator_insight = curator_insight
        if summary_prompt_json is not None:
            item.summary_prompt_json = summary_prompt_json
        if model_response_json is not None:
            item.model_response_json = model_response_json
        item.updated_at = _utcnow()
        return replace(item)

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
    ) -> ExtractionJob | None:
        job = self._jobs.get(job_id)
        if not job:
            return None
        if status is not None:
            job.status = status
        if stage is not None:
            job.stage = stage
        if progress_percent is not None:
            job.progress_percent = progress_percent
        if error_code is not None:
            job.error_code = error_code
        if error_message is not None:
            job.error_message = error_message
        if attempt is not None:
            job.attempt = attempt
        if next_retry_at_iso is not None:
            job.next_retry_at = datetime.fromisoformat(next_retry_at_iso.replace("Z", "+00:00"))
        if clear_next_retry_at:
            job.next_retry_at = None
        if clear_error_fields:
            job.error_code = None
            job.error_message = None
        if status in ("completed", "failed", "dead_letter", "queued"):
            job.locked_until = None
        job.updated_at = _utcnow()
        return replace(job)

    async def upsert_locations(self, content_id: str, locations: list[Location]) -> None:
        self._locations_by_content[content_id] = [replace(l, content_id=content_id) for l in locations]
        item = self._content.get(content_id)
        if item:
            item.updated_at = _utcnow()

    async def list_map_locations(self, owner_user_id: str) -> list[Location]:
        allowed_content_ids = {c.id for c in self._content.values() if c.owner_user_id == owner_user_id}
        out: list[Location] = []
        for content_id in allowed_content_ids:
            out.extend(self._locations_by_content.get(content_id, []))
        return [replace(x) for x in out]

    async def list_locations_for_content(self, content_id: str, owner_user_id: str) -> list[Location]:
        item = self._content.get(content_id)
        if not item or item.owner_user_id != owner_user_id:
            return []
        return [replace(x) for x in self._locations_by_content.get(content_id, [])]

    async def add_bookmark(self, owner_user_id: str, content_id: str) -> None:
        self._bookmarks.add((owner_user_id, content_id))

    async def list_bookmark_content_ids(self, owner_user_id: str) -> list[str]:
        return sorted({cid for (uid, cid) in self._bookmarks if uid == owner_user_id})

    async def upsert_menu_items(
        self, content_id: str, owner_user_id: str, items: list[ExtractedMenuItem]
    ) -> None:
        item = self._content.get(content_id)
        if not item or item.owner_user_id != owner_user_id:
            return
        self._menu_items[content_id] = [replace(m, content_id=content_id) for m in items]

    async def list_menu_items(self, content_id: str, owner_user_id: str) -> list[ExtractedMenuItem]:
        item = self._content.get(content_id)
        if not item or item.owner_user_id != owner_user_id:
            return []
        return [replace(m) for m in self._menu_items.get(content_id, [])]

    def seed_menu_items(self, content_id: str, items: list[ExtractedMenuItem]) -> None:
        """Test helper: attach menu rows to content."""
        self._menu_items[content_id] = [replace(m, content_id=content_id) for m in items]

    async def search_content(
        self,
        owner_user_id: str,
        *,
        q: str | None = None,
        smart: str | None = None,
        max_results: int = 500,
    ) -> list[ContentItem]:
        rows = [c for c in self._content.values() if c.owner_user_id == owner_user_id]
        qq = _norm_q(q)

        def match_text(c: ContentItem) -> bool:
            if not qq:
                return True
            parts = [
                c.title_generated or "",
                c.title_original or "",
                c.summary_text or "",
                " ".join(c.semantic_tags or []),
                " ".join(c.mood_tags or []),
            ]
            blob = " ".join(parts).lower()
            return qq in blob

        if smart == "to_visit":
            bids = set(await self.list_bookmark_content_ids(owner_user_id))
            rows = [c for c in rows if c.id in bids and c.status == "ready"]
        elif smart == "recent":
            rows = [c for c in rows if c.status == "ready"]
        elif smart == "reels":
            rows = [c for c in rows if c.source_type == "reel"]
        elif smart == "posts":
            rows = [c for c in rows if c.source_type == "post"]

        rows = [c for c in rows if match_text(c)]
        rows.sort(key=lambda x: x.created_at, reverse=True)
        return [replace(x) for x in rows[:max_results]]

    async def list_collections(self, owner_user_id: str, limit: int, offset: int) -> list[Collection]:
        rows = [c for c in self._collections.values() if c.owner_user_id == owner_user_id]
        rows.sort(key=lambda x: x.updated_at, reverse=True)
        return [replace(x) for x in rows[offset : offset + limit]]

    async def create_collection(
        self,
        owner_user_id: str,
        name: str,
        description: str | None,
        collection_type: str,
        cover_image_url: str | None,
    ) -> Collection:
        c = Collection(
            owner_user_id=owner_user_id,
            name=name,
            description=description,
            cover_image_url=cover_image_url,
            collection_type=collection_type,
        )
        self._collections[c.id] = c
        self._collection_items[c.id] = []
        return replace(c)

    async def get_collection(self, collection_id: str, owner_user_id: str) -> Collection | None:
        c = self._collections.get(collection_id)
        if not c or c.owner_user_id != owner_user_id:
            return None
        return replace(c)

    async def update_collection(
        self,
        collection_id: str,
        owner_user_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        cover_image_url: str | None = None,
    ) -> Collection | None:
        c = self._collections.get(collection_id)
        if not c or c.owner_user_id != owner_user_id:
            return None
        if name is not None:
            c.name = name
        if description is not None:
            c.description = description
        if cover_image_url is not None:
            c.cover_image_url = cover_image_url
        c.updated_at = _utcnow()
        return replace(c)

    async def delete_collection(self, collection_id: str, owner_user_id: str) -> bool:
        c = self._collections.get(collection_id)
        if not c or c.owner_user_id != owner_user_id:
            return False
        del self._collections[collection_id]
        self._collection_items.pop(collection_id, None)
        return True

    async def add_collection_item(self, collection_id: str, owner_user_id: str, content_id: str) -> None:
        c = self._collections.get(collection_id)
        if not c or c.owner_user_id != owner_user_id:
            raise ValueError("collection_not_found")
        item = self._content.get(content_id)
        if not item or item.owner_user_id != owner_user_id:
            raise ValueError("content_not_found")
        lst = self._collection_items.setdefault(collection_id, [])
        if content_id not in lst:
            lst.append(content_id)
        c.updated_at = _utcnow()

    async def remove_collection_item(self, collection_id: str, owner_user_id: str, content_id: str) -> None:
        c = self._collections.get(collection_id)
        if not c or c.owner_user_id != owner_user_id:
            raise ValueError("collection_not_found")
        lst = self._collection_items.setdefault(collection_id, [])
        if content_id in lst:
            lst.remove(content_id)
        c.updated_at = _utcnow()

    async def list_collection_items(
        self, collection_id: str, owner_user_id: str, limit: int, offset: int
    ) -> list[ContentItem]:
        c = self._collections.get(collection_id)
        if not c or c.owner_user_id != owner_user_id:
            return []
        order = self._collection_items.get(collection_id, [])
        # preserve insertion order (newest at end); show recent first
        ids = list(reversed(order))
        slice_ids = ids[offset : offset + limit]
        out: list[ContentItem] = []
        for cid in slice_ids:
            item = self._content.get(cid)
            if item:
                out.append(replace(item))
        return out
