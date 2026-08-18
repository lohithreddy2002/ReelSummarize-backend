"""
Phase 1 application service for content lifecycle operations.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

from domain.models import ContentItem, ExtractedMenuItem
from ports.persistence import PersistencePort
from services.downloader import downloader
from services.geocoder import geocoder
from services.location_merge import merge_locations_for_content
from services.summarizer import extract_title_from_summary, get_summarizer


def _log_stage(stage: str, t0: float) -> None:
    elapsed_ms = (time.monotonic() - t0) * 1000.0
    logger.info("stage=%s elapsed_ms=%.1f", stage, elapsed_ms)


class ContentService:
    def __init__(self, persistence: PersistencePort) -> None:
        self.persistence = persistence

    async def ingest_content(self, owner_user_id: str, source_url: str) -> dict:
        content = await self.persistence.create_content(owner_user_id=owner_user_id, source_url=source_url)
        job = await self.persistence.create_extraction_job(content.id)
        return {"content": content, "job": job}

    async def get_status(self, owner_user_id: str, content_id: str) -> dict | None:
        content = await self.persistence.get_content(content_id, owner_user_id)
        if not content:
            return None
        job = await self.persistence.get_latest_job_by_content(content_id)
        return {"content": content, "job": job}

    async def get_content_detail(self, owner_user_id: str, content_id: str):
        return await self.persistence.get_content(content_id, owner_user_id)

    async def get_feed(self, owner_user_id: str, limit: int, offset: int):
        return await self.persistence.list_feed(owner_user_id, limit, offset)

    async def get_map_locations(self, owner_user_id: str):
        return await self.persistence.list_map_locations(owner_user_id)

    async def list_active_extractions(self, owner_user_id: str, *, limit: int = 50) -> list[ContentItem]:
        return await self.persistence.list_active_extractions(owner_user_id, limit=limit)

    async def get_locations_for_content(self, owner_user_id: str, content_id: str):
        return await self.persistence.list_locations_for_content(content_id, owner_user_id)

    async def bookmark(self, owner_user_id: str, content_id: str) -> bool:
        content = await self.persistence.get_content(content_id, owner_user_id)
        if not content:
            return False
        await self.persistence.add_bookmark(owner_user_id, content_id)
        return True

    async def cancel_extraction(self, owner_user_id: str, content_id: str) -> bool:
        return await self.persistence.cancel_extraction_for_user(owner_user_id, content_id)

    async def delete_content(self, owner_user_id: str, content_id: str) -> bool:
        return await self.persistence.delete_content(content_id, owner_user_id)

    async def enrich_content_now(self, owner_user_id: str, content_id: str) -> None:
        """Synchronous enrichment: metadata, summary, and extracted locations, computed inline."""
        content = await self.persistence.get_content(content_id, owner_user_id)
        if not content:
            return
        if content.status == "ready":
            return
        job = await self.persistence.get_latest_job_by_content(content_id)
        if not job:
            return

        await self.persistence.update_content(content_id, owner_user_id, status="processing")
        await self.persistence.update_job(job.id, status="processing", stage="metadata", progress_percent=15)
        try:
            t0 = time.monotonic()
            info = await downloader.get_media_info(content.source_url)
            _log_stage("metadata_fetch", t0)

            await self.persistence.update_job(job.id, stage="summarizing", progress_percent=45)
            summarizer = get_summarizer()
            t1 = time.monotonic()
            result = await summarizer.summarize(video_path=None, metadata=info, prefer_video=False)
            _log_stage("summarize", t1)
            summary = result.get("summary") if result.get("success") else None
            title_generated = result.get("title")
            if not title_generated:
                title_generated, _ = extract_title_from_summary(summary or "")

            structured_locations = result.get("locations") or []
            location_names = [str(x.get("name", "")).strip() for x in structured_locations if isinstance(x, dict)]
            location_names = [x for x in location_names if x]
            if not location_names:
                location_names = geocoder.extract_locations_from_text(summary or "")
            logger.info("geocoding: %d location(s) to resolve for content %s: %s", len(location_names), content_id, location_names)
            t_geo = time.monotonic()
            merged_locations = (
                await merge_locations_for_content(
                    content_id, location_names, structured_locations, geocoder_svc=geocoder
                )
                if location_names
                else []
            )
            _log_stage("geocode_merge", t_geo)
            n_ok = sum(1 for loc in merged_locations if loc.geocoded)
            logger.info("geocoding: resolved %d/%d locations for content %s", n_ok, len(merged_locations), content_id)
            await self.persistence.upsert_locations(content_id, merged_locations)

            menu_items_raw = result.get("menu_items") or []
            menu_items = [
                ExtractedMenuItem(
                    content_id=content_id,
                    name=str(m.get("name", "")).strip(),
                    item_type=m.get("item_type"),
                    currency=m.get("currency"),
                    price_value=m.get("price_value"),
                    price_display=m.get("price_display"),
                    price_confidence=m.get("price_confidence"),
                )
                for m in menu_items_raw
                if isinstance(m, dict) and str(m.get("name", "")).strip()
            ]
            await self.persistence.upsert_menu_items(content_id, owner_user_id, menu_items)

            if result.get("success"):
                prompt_snapshot = result.get("summary_prompt_json")
                model_payload = {k: v for k, v in result.items() if k != "summary_prompt_json"}
                await self.persistence.update_content(
                    content_id,
                    owner_user_id,
                    status="ready",
                    title_original=info.get("title"),
                    title_generated=title_generated,
                    summary_text=summary,
                    summary_method=result.get("method"),
                    thumbnail_url=info.get("thumbnail"),
                    likes_count=info.get("like_count"),
                    comments_count=info.get("comment_count"),
                    views_count=info.get("view_count"),
                    semantic_tags=result.get("semantic_tags") or [],
                    mood_tags=result.get("mood_tags") or [],
                    curator_insight=result.get("curator_insight"),
                    summary_prompt_json=prompt_snapshot,
                    model_response_json=model_payload,
                )
                await self.persistence.update_job(job.id, status="completed", stage="completed", progress_percent=100)
            else:
                err = result.get("error") or "summarization_failed"
                await self.persistence.update_content(content_id, owner_user_id, status="error")
                await self.persistence.update_job(
                    job.id,
                    status="failed",
                    stage="failed",
                    progress_percent=100,
                    error_code="SUMMARIZATION_FAILED",
                    error_message=err,
                )
        except Exception as exc:
            await self.persistence.update_content(content_id, owner_user_id, status="error")
            await self.persistence.update_job(
                job.id,
                status="failed",
                stage="failed",
                progress_percent=100,
                error_code="CONTENT_ENRICHMENT_FAILED",
                error_message=str(exc),
            )
            raise
