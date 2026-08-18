"""
Supabase REST persistence adapter for Phase 1 endpoints.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

from domain.models import Collection, ContentItem, ExtractionJob, ExtractedMenuItem, Location
from ports.persistence import PersistencePort


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.utcnow()
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _text_array(row: dict[str, Any], key: str) -> list[str] | None:
    v = row.get(key)
    if v is None:
        return None
    if isinstance(v, list):
        return [str(x) for x in v]
    return None


def _location_row_latlng(row: dict[str, Any]) -> tuple[float | None, float | None]:
    la, ln = row.get("lat"), row.get("lng")
    if la is None or ln is None:
        return None, None
    try:
        return float(la), float(ln)
    except (TypeError, ValueError):
        return None, None


def _domain_location_from_row(r: dict[str, Any]) -> Location:
    lat, lng = _location_row_latlng(r)
    gc = r.get("geocoded")
    if gc is None:
        geocoded = lat is not None and lng is not None
    else:
        geocoded = bool(gc)
    return Location(
        id=r["id"],
        content_id=r["content_id"],
        name=r["name"],
        display_name=r.get("display_name"),
        lat=lat,
        lng=lng,
        geocoded=geocoded,
        rating=r.get("rating"),
        review_count=r.get("review_count"),
        place_category=r.get("place_category"),
        image_url=r.get("image_url"),
    )


def _parse_dt_optional(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _extraction_job_from_row(row: dict[str, Any]) -> ExtractionJob:
    return ExtractionJob(
        id=row["id"],
        content_id=row["content_id"],
        status=row.get("status") or "queued",
        stage=row.get("stage") or "queued",
        progress_percent=row.get("progress_percent") or 0,
        attempt=row.get("attempt") or 0,
        max_attempts=row.get("max_attempts") or 3,
        error_code=row.get("error_code"),
        error_message=row.get("error_message"),
        locked_until=_parse_dt_optional(row.get("locked_until")),
        next_retry_at=_parse_dt_optional(row.get("next_retry_at")),
        created_at=_parse_dt(row.get("created_at")),
        updated_at=_parse_dt(row.get("updated_at")),
    )


def _content_item_from_row(row: dict[str, Any]) -> ContentItem:
    return ContentItem(
        id=row["id"],
        owner_user_id=row["owner_user_id"],
        source_url=row["source_url"],
        source_platform=row.get("source_platform") or "unknown",
        source_type=row.get("source_type") or "reel",
        status=row.get("status") or "queued",
        title_original=row.get("title_original"),
        title_generated=row.get("title_generated"),
        summary_text=row.get("summary_text"),
        summary_method=row.get("summary_method"),
        thumbnail_url=row.get("thumbnail_url"),
        likes_count=row.get("likes_count"),
        comments_count=row.get("comments_count"),
        views_count=row.get("views_count"),
        semantic_tags=_text_array(row, "semantic_tags"),
        mood_tags=_text_array(row, "mood_tags"),
        curator_insight=row.get("curator_insight"),
        summary_prompt_json=row.get("summary_prompt_json"),
        model_response_json=row.get("model_response_json"),
        created_at=_parse_dt(row.get("created_at")),
        updated_at=_parse_dt(row.get("updated_at")),
    )


def _collection_from_row(row: dict[str, Any]) -> Collection:
    return Collection(
        id=row["id"],
        owner_user_id=row["owner_user_id"],
        name=row["name"],
        description=row.get("description"),
        cover_image_url=row.get("cover_image_url"),
        collection_type=row.get("collection_type") or "custom",
        created_at=_parse_dt(row.get("created_at")),
        updated_at=_parse_dt(row.get("updated_at")),
    )


class SupabasePersistenceAdapter(PersistencePort):
    def __init__(self, url: str, secret_key: str) -> None:
        self._base = f"{url.rstrip('/')}/rest/v1"
        self._headers = {
            "apikey": secret_key,
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        # Shared client with connection pooling — avoids TCP handshake overhead per request.
        # limits: 10 keepalive + 20 max connections is appropriate for a low-traffic API.
        self._client = httpx.AsyncClient(
            timeout=20.0,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )

    async def _request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None, json: Any = None
    ) -> list[dict[str, Any]]:
        response = await self._client.request(
            method, f"{self._base}/{path}", headers=self._headers, params=params, json=json
        )
        if response.status_code == 401:
            logger.error(
                "Supabase REST returned 401 Unauthorized for %s. "
                "Set SUPABASE_SECRET_KEY to the project secret key from "
                "Supabase Dashboard → Project Settings → API (not the publishable key). "
                "Remove surrounding quotes/whitespace in .env; redeploy after fixing.",
                path,
            )
        response.raise_for_status()
        if not response.text:
            return []
        data = response.json()
        return data if isinstance(data, list) else [data]

    async def create_content(self, owner_user_id: str, source_url: str) -> ContentItem:
        platform = "instagram" if "instagram.com" in source_url else "unknown"
        payload = {
            "owner_user_id": owner_user_id,
            "source_url": source_url,
            "source_platform": platform,
            "source_type": "reel",
            "status": "queued",
        }
        rows = await self._request("POST", "content_items", json=payload)
        row = rows[0]
        return _content_item_from_row(row)

    async def get_content(self, content_id: str, owner_user_id: str) -> Optional[ContentItem]:
        rows = await self._request(
            "GET",
            "content_items",
            params={
                "id": f"eq.{content_id}",
                "owner_user_id": f"eq.{owner_user_id}",
                "select": "*",
                "limit": "1",
            },
        )
        if not rows:
            return None
        row = rows[0]
        return _content_item_from_row(row)

    async def list_feed(self, owner_user_id: str, limit: int, offset: int) -> list[ContentItem]:
        rows = await self._request(
            "GET",
            "content_items",
            params={
                "owner_user_id": f"eq.{owner_user_id}",
                "select": "*",
                "order": "created_at.desc",
                "limit": str(limit),
                "offset": str(offset),
            },
        )
        return [_content_item_from_row(r) for r in rows]

    async def create_extraction_job(self, content_id: str) -> ExtractionJob:
        rows = await self._request("POST", "extraction_jobs", json={"content_id": content_id, "status": "queued"})
        row = rows[0]
        return _extraction_job_from_row(row)

    async def get_latest_job_by_content(self, content_id: str) -> Optional[ExtractionJob]:
        rows = await self._request(
            "GET",
            "extraction_jobs",
            params={"content_id": f"eq.{content_id}", "order": "created_at.desc", "limit": "1", "select": "*"},
        )
        if not rows:
            return None
        return _extraction_job_from_row(rows[0])

    async def get_content_by_id(self, content_id: str) -> Optional[ContentItem]:
        rows = await self._request(
            "GET",
            "content_items",
            params={"id": f"eq.{content_id}", "select": "*", "limit": "1"},
        )
        if not rows:
            return None
        return _content_item_from_row(rows[0])

    async def _count_jobs(self, extra_params: dict[str, str]) -> int:
        params: dict[str, str] = {"select": "id", "limit": "1", **extra_params}
        response = await self._client.get(
            f"{self._base}/extraction_jobs",
            headers={**self._headers, "Prefer": "count=exact"},
            params=params,
        )
        response.raise_for_status()
        cr = response.headers.get("content-range") or ""
        if "/" in cr:
            try:
                return int(cr.split("/")[-1])
            except ValueError:
                return 0
        return 0

    async def list_active_extractions(self, owner_user_id: str, *, limit: int = 50) -> list[ContentItem]:
        rows = await self._request(
            "GET",
            "content_items",
            params={
                "owner_user_id": f"eq.{owner_user_id}",
                "status": "in.(queued,processing)",
                "select": "*",
                "order": "created_at.desc",
                "limit": str(limit),
            },
        )
        return [_content_item_from_row(r) for r in rows]

    async def get_extraction_job_by_id(self, job_id: str) -> Optional[ExtractionJob]:
        rows = await self._request(
            "GET",
            "extraction_jobs",
            params={"id": f"eq.{job_id}", "select": "*", "limit": "1"},
        )
        if not rows:
            return None
        return _extraction_job_from_row(rows[0])


    async def admin_force_requeue_job(self, job_id: str) -> bool:
        job = await self.get_extraction_job_by_id(job_id)
        if not job:
            return False
        await self.update_job(
            job_id,
            status="queued",
            stage="queued",
            progress_percent=0,
            attempt=0,
            clear_next_retry_at=True,
            clear_error_fields=True,
        )
        content = await self.get_content_by_id(job.content_id)
        if content:
            await self.update_content(job.content_id, content.owner_user_id, status="queued")
        return True

    async def cancel_extraction_for_user(self, owner_user_id: str, content_id: str) -> bool:
        content = await self.get_content(content_id, owner_user_id)
        if not content or content.status not in ("queued", "processing"):
            return False
        job = await self.get_latest_job_by_content(content_id)
        if job and job.status not in ("completed", "dead_letter"):
            await self.update_job(
                job.id,
                status="failed",
                stage="cancelled",
                progress_percent=100,
                error_code="USER_CANCELLED",
                error_message="Cancelled by user",
            )
        await self.update_content(content_id, owner_user_id, status="error")
        return True

    async def list_stuck_extraction_job_ids(self, *, older_than_minutes: int, limit: int = 200) -> list[str]:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)).isoformat()
        rows = await self._request(
            "GET",
            "extraction_jobs",
            params={
                "status": "eq.processing",
                "updated_at": f"lt.{cutoff}",
                "select": "id",
                "order": "updated_at.asc",
                "limit": str(limit),
            },
        )
        return [str(r["id"]) for r in rows]

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
        payload: dict[str, Any] = {}
        if status is not None:
            payload["status"] = status
        if title_original is not None:
            payload["title_original"] = title_original
        if title_generated is not None:
            payload["title_generated"] = title_generated
        if summary_text is not None:
            payload["summary_text"] = summary_text
        if summary_method is not None:
            payload["summary_method"] = summary_method
        if thumbnail_url is not None:
            payload["thumbnail_url"] = thumbnail_url
        if likes_count is not None:
            payload["likes_count"] = likes_count
        if comments_count is not None:
            payload["comments_count"] = comments_count
        if views_count is not None:
            payload["views_count"] = views_count
        if semantic_tags is not None:
            payload["semantic_tags"] = semantic_tags
        if mood_tags is not None:
            payload["mood_tags"] = mood_tags
        if curator_insight is not None:
            payload["curator_insight"] = curator_insight
        if summary_prompt_json is not None:
            payload["summary_prompt_json"] = summary_prompt_json
        if model_response_json is not None:
            payload["model_response_json"] = model_response_json
        if not payload:
            return await self.get_content(content_id, owner_user_id)
        rows = await self._request(
            "PATCH",
            "content_items",
            params={"id": f"eq.{content_id}", "owner_user_id": f"eq.{owner_user_id}", "select": "*"},
            json=payload,
        )
        if not rows:
            return None
        row = rows[0]
        return _content_item_from_row(row)

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
        payload: dict[str, Any] = {}
        if status is not None:
            payload["status"] = status
        if stage is not None:
            payload["stage"] = stage
        if progress_percent is not None:
            payload["progress_percent"] = progress_percent
        if error_code is not None:
            payload["error_code"] = error_code
        if error_message is not None:
            payload["error_message"] = error_message
        if attempt is not None:
            payload["attempt"] = attempt
        if next_retry_at_iso is not None:
            payload["next_retry_at"] = next_retry_at_iso
        if clear_next_retry_at:
            payload["next_retry_at"] = None
        if clear_error_fields:
            payload["error_code"] = None
            payload["error_message"] = None
        if not payload:
            rows = await self._request("GET", "extraction_jobs", params={"id": f"eq.{job_id}", "select": "*", "limit": "1"})
            if not rows:
                return None
            row = rows[0]
        else:
            if status in ("completed", "failed", "dead_letter", "queued"):
                payload["locked_until"] = None
            rows = await self._request(
                "PATCH",
                "extraction_jobs",
                params={"id": f"eq.{job_id}", "select": "*"},
                json=payload,
            )
            if not rows:
                return None
            row = rows[0]

        return _extraction_job_from_row(row)

    async def upsert_locations(self, content_id: str, locations: list[Location]) -> None:
        await self._request("DELETE", "locations", params={"content_id": f"eq.{content_id}"})
        if not locations:
            return
        rows = [
            {
                "content_id": content_id,
                "name": loc.name,
                "display_name": loc.display_name,
                "lat": loc.lat,
                "lng": loc.lng,
                "geocoded": loc.geocoded,
                "rating": loc.rating,
                "review_count": loc.review_count,
                "place_category": loc.place_category,
                "image_url": loc.image_url,
            }
            for loc in locations
        ]
        await self._request("POST", "locations", json=rows)

    async def list_map_locations(self, owner_user_id: str) -> list[Location]:
        rows = await self._request(
            "GET",
            "locations",
            params={
                "select": "id,content_id,name,display_name,lat,lng,geocoded,rating,review_count,place_category,image_url,content_items!inner(owner_user_id)",
                "content_items.owner_user_id": f"eq.{owner_user_id}",
                "limit": "500",
            },
        )
        return [_domain_location_from_row(r) for r in rows]

    async def list_locations_for_content(self, content_id: str, owner_user_id: str) -> list[Location]:
        rows = await self._request(
            "GET",
            "locations",
            params={
                "content_id": f"eq.{content_id}",
                "select": "id,content_id,name,display_name,lat,lng,geocoded,rating,review_count,place_category,image_url,content_items!inner(owner_user_id)",
                "content_items.owner_user_id": f"eq.{owner_user_id}",
            },
        )
        return [_domain_location_from_row(r) for r in rows]

    async def add_bookmark(self, owner_user_id: str, content_id: str) -> None:
        await self._request(
            "POST",
            "bookmarks",
            json={"owner_user_id": owner_user_id, "content_id": content_id},
        )

    async def list_bookmark_content_ids(self, owner_user_id: str) -> list[str]:
        rows = await self._request(
            "GET",
            "bookmarks",
            params={"owner_user_id": f"eq.{owner_user_id}", "select": "content_id"},
        )
        return [str(r["content_id"]) for r in rows]

    async def upsert_menu_items(
        self, content_id: str, owner_user_id: str, items: list[ExtractedMenuItem]
    ) -> None:
        await self._request("DELETE", "menu_items", params={"content_id": f"eq.{content_id}"})
        if not items:
            return
        payload = [
            {
                "content_id": content_id,
                "name": m.name,
                "item_type": m.item_type,
                "currency": m.currency,
                "price_value": m.price_value,
                "price_display": m.price_display,
                "price_confidence": m.price_confidence,
            }
            for m in items
            if m.name
        ]
        if payload:
            await self._request("POST", "menu_items", json=payload)

    async def list_menu_items(self, content_id: str, owner_user_id: str) -> list[ExtractedMenuItem]:
        owner = await self.get_content(content_id, owner_user_id)
        if not owner:
            return []
        rows = await self._request(
            "GET",
            "menu_items",
            params={
                "content_id": f"eq.{content_id}",
                "select": "id,content_id,location_id,name,item_type,currency,price_value,price_display,price_confidence",
            },
        )
        return [
            ExtractedMenuItem(
                id=r["id"],
                content_id=r["content_id"],
                location_id=r.get("location_id"),
                name=r["name"],
                item_type=r.get("item_type"),
                currency=r.get("currency"),
                price_value=float(r["price_value"]) if r.get("price_value") is not None else None,
                price_display=r.get("price_display"),
                price_confidence=float(r["price_confidence"]) if r.get("price_confidence") is not None else None,
            )
            for r in rows
        ]

    async def search_content(
        self,
        owner_user_id: str,
        *,
        q: str | None = None,
        smart: str | None = None,
        max_results: int = 500,
    ) -> list[ContentItem]:
        cap = min(max_results, 500)
        params: dict[str, str] = {
            "owner_user_id": f"eq.{owner_user_id}",
            "select": "*",
            "order": "created_at.desc",
            "limit": str(cap),
        }

        # Push smart filters to DB — avoids fetching all rows and filtering in Python
        if smart == "recent":
            params["status"] = "eq.ready"
        elif smart == "reels":
            params["source_type"] = "eq.reel"
        elif smart == "posts":
            params["source_type"] = "eq.post"
        elif smart == "to_visit":
            bids = await self.list_bookmark_content_ids(owner_user_id)
            if not bids:
                return []
            params["id"] = f"in.({','.join(bids)})"
            params["status"] = "eq.ready"

        # Push text filter to DB — hits the existing gin_trgm indexes
        qq = (q or "").strip()
        if qq:
            escaped = qq.replace("%", r"\%").replace("_", r"\_")
            params["or"] = (
                f"(title_generated.ilike.*{escaped}*,"
                f"title_original.ilike.*{escaped}*,"
                f"summary_text.ilike.*{escaped}*)"
            )

        rows = await self._request("GET", "content_items", params=params)
        return [_content_item_from_row(r) for r in rows]

    async def list_collections(self, owner_user_id: str, limit: int, offset: int) -> list[Collection]:
        rows = await self._request(
            "GET",
            "collections",
            params={
                "owner_user_id": f"eq.{owner_user_id}",
                "select": "*",
                "order": "updated_at.desc",
                "limit": str(limit),
                "offset": str(offset),
            },
        )
        return [_collection_from_row(r) for r in rows]

    async def create_collection(
        self,
        owner_user_id: str,
        name: str,
        description: str | None,
        collection_type: str,
        cover_image_url: str | None,
    ) -> Collection:
        payload: dict[str, Any] = {
            "owner_user_id": owner_user_id,
            "name": name,
            "collection_type": collection_type,
        }
        if description is not None:
            payload["description"] = description
        if cover_image_url is not None:
            payload["cover_image_url"] = cover_image_url
        rows = await self._request("POST", "collections", json=payload)
        return _collection_from_row(rows[0])

    async def get_collection(self, collection_id: str, owner_user_id: str) -> Optional[Collection]:
        rows = await self._request(
            "GET",
            "collections",
            params={
                "id": f"eq.{collection_id}",
                "owner_user_id": f"eq.{owner_user_id}",
                "select": "*",
                "limit": "1",
            },
        )
        if not rows:
            return None
        return _collection_from_row(rows[0])

    async def update_collection(
        self,
        collection_id: str,
        owner_user_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        cover_image_url: str | None = None,
    ) -> Optional[Collection]:
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if description is not None:
            payload["description"] = description
        if cover_image_url is not None:
            payload["cover_image_url"] = cover_image_url
        if not payload:
            return await self.get_collection(collection_id, owner_user_id)
        rows = await self._request(
            "PATCH",
            "collections",
            params={"id": f"eq.{collection_id}", "owner_user_id": f"eq.{owner_user_id}", "select": "*"},
            json=payload,
        )
        if not rows:
            return None
        return _collection_from_row(rows[0])

    async def delete_content(self, content_id: str, owner_user_id: str) -> bool:
        rows = await self._request(
            "GET",
            "content_items",
            params={"id": f"eq.{content_id}", "owner_user_id": f"eq.{owner_user_id}", "select": "id", "limit": "1"},
        )
        if not rows:
            return False
        # ON DELETE CASCADE handles locations, menu_items, extraction_jobs automatically
        await self._request(
            "DELETE",
            "content_items",
            params={"id": f"eq.{content_id}", "owner_user_id": f"eq.{owner_user_id}"},
        )
        return True

    async def delete_collection(self, collection_id: str, owner_user_id: str) -> bool:
        rows = await self._request(
            "GET",
            "collections",
            params={"id": f"eq.{collection_id}", "owner_user_id": f"eq.{owner_user_id}", "select": "id", "limit": "1"},
        )
        if not rows:
            return False
        await self._request(
            "DELETE",
            "collections",
            params={"id": f"eq.{collection_id}", "owner_user_id": f"eq.{owner_user_id}"},
        )
        return True

    async def add_collection_item(self, collection_id: str, owner_user_id: str, content_id: str) -> None:
        c = await self.get_collection(collection_id, owner_user_id)
        if not c:
            raise ValueError("collection_not_found")
        rows = await self._request(
            "GET",
            "content_items",
            params={"id": f"eq.{content_id}", "owner_user_id": f"eq.{owner_user_id}", "select": "id", "limit": "1"},
        )
        if not rows:
            raise ValueError("content_not_found")
        await self._request(
            "POST",
            "collection_items",
            json={"collection_id": collection_id, "content_id": content_id},
        )

    async def remove_collection_item(self, collection_id: str, owner_user_id: str, content_id: str) -> None:
        c = await self.get_collection(collection_id, owner_user_id)
        if not c:
            raise ValueError("collection_not_found")
        await self._request(
            "DELETE",
            "collection_items",
            params={"collection_id": f"eq.{collection_id}", "content_id": f"eq.{content_id}"},
        )

    async def list_collection_items(
        self, collection_id: str, owner_user_id: str, limit: int, offset: int
    ) -> list[ContentItem]:
        # Call 1: verify collection ownership
        c = await self.get_collection(collection_id, owner_user_id)
        if not c:
            return []
        # Call 2: fetch items + embedded content rows in one PostgREST request
        rows = await self._request(
            "GET",
            "collection_items",
            params={
                "collection_id": f"eq.{collection_id}",
                "select": "added_at,content_items!inner(*)",
                "content_items.owner_user_id": f"eq.{owner_user_id}",
                "order": "added_at.desc",
                "limit": str(limit),
                "offset": str(offset),
            },
        )
        return [
            _content_item_from_row(r["content_items"])
            for r in rows
            if isinstance(r.get("content_items"), dict)
        ]
