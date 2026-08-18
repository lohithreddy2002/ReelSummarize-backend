"""
Domain models for canonical Phase 1 content lifecycle.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ContentItem:
    id: str = field(default_factory=lambda: str(uuid4()))
    owner_user_id: str = "anonymous"
    source_url: str = ""
    source_platform: str = "unknown"
    source_type: str = "video"
    status: str = "queued"
    title_original: Optional[str] = None
    title_generated: Optional[str] = None
    summary_text: Optional[str] = None
    summary_method: Optional[str] = None
    thumbnail_url: Optional[str] = None
    likes_count: Optional[int] = None
    comments_count: Optional[int] = None
    views_count: Optional[int] = None
    semantic_tags: Optional[list[str]] = None
    mood_tags: Optional[list[str]] = None
    curator_insight: Optional[str] = None
    summary_prompt_json: Optional[dict[str, Any]] = None
    model_response_json: Optional[dict[str, Any]] = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class ExtractionJob:
    id: str = field(default_factory=lambda: str(uuid4()))
    content_id: str = ""
    status: str = "queued"
    stage: str = "queued"
    progress_percent: int = 0
    attempt: int = 0
    max_attempts: int = 3
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    locked_until: Optional[datetime] = None
    next_retry_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class Location:
    id: str = field(default_factory=lambda: str(uuid4()))
    content_id: str = ""
    name: str = ""
    display_name: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    geocoded: bool = True
    rating: Optional[float] = None
    review_count: Optional[int] = None
    place_category: Optional[str] = None
    image_url: Optional[str] = None


@dataclass
class ExtractedMenuItem:
    id: str = field(default_factory=lambda: str(uuid4()))
    content_id: str = ""
    location_id: Optional[str] = None
    name: str = ""
    item_type: Optional[str] = None
    currency: Optional[str] = None
    price_value: Optional[float] = None
    price_display: Optional[str] = None
    price_confidence: Optional[float] = None


@dataclass
class Collection:
    id: str = field(default_factory=lambda: str(uuid4()))
    owner_user_id: str = "anonymous"
    name: str = ""
    description: Optional[str] = None
    cover_image_url: Optional[str] = None
    collection_type: str = "custom"
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

