"""
Pydantic schemas for API request/response validation
"""
from typing import Optional, Literal, List
from pydantic import BaseModel, HttpUrl, Field


class SummarizeRequest(BaseModel):
    """Request schema for summarization endpoint"""
    url: str = Field(..., description="URL of the reel/video to summarize")
    prefer_video_analysis: bool = Field(
        default=True,
        description="Whether to prefer video analysis over metadata-only"
    )


class MediaInfo(BaseModel):
    """Schema for media information"""
    id: str
    title: Optional[str] = None
    description: Optional[str] = None
    duration: Optional[float] = None
    uploader: Optional[str] = None
    thumbnail: Optional[str] = None
    platform: Optional[str] = None
    video_url: Optional[str] = None  # Direct video URL for local download


class LocationInfo(BaseModel):
    """Schema for a place: coordinates optional when geocoding failed or was skipped."""
    name: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    display_name: Optional[str] = None
    geocoded: bool = True


class SummarizeResponse(BaseModel):
    """Response schema for summarization endpoint"""
    success: bool
    url: str
    summary: Optional[str] = None
    generated_title: Optional[str] = None  # AI-generated title from the summary
    method: Literal['video_analysis', 'metadata_analysis', 'failed', 'none']
    media_info: Optional[MediaInfo] = None
    locations: Optional[List[LocationInfo]] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Response schema for health check"""
    status: str
    version: str
    gemini_configured: bool


class InfoRequest(BaseModel):
    """Request schema for info endpoint"""
    url: str = Field(..., description="URL to get information about")


class InfoResponse(BaseModel):
    """Response schema for info endpoint"""
    success: bool
    media_info: Optional[MediaInfo] = None
    error: Optional[str] = None


class ReelData(BaseModel):
    """Schema for reel data in search request"""
    id: str
    url: str
    title: Optional[str] = None
    summary: Optional[str] = None
    locations: Optional[List[LocationInfo]] = None


class SearchLocationsRequest(BaseModel):
    """Request schema for semantic location search"""
    query: str = Field(..., description="Search query (e.g., 'winter destinations', 'beach vacation')")
    reels: List[ReelData] = Field(..., description="List of saved reels to search through")


class MatchedLocation(BaseModel):
    """Schema for a location that matches the search query"""
    name: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    display_name: Optional[str] = None
    geocoded: bool = True
    source_url: str
    source_title: Optional[str] = None
    reel_id: str
    relevance_reason: Optional[str] = None


class SearchLocationsResponse(BaseModel):
    """Response schema for location search"""
    success: bool
    query: str
    matched_locations: List[MatchedLocation] = []
    total_matches: int = 0
    error: Optional[str] = None


class GeocodeRequest(BaseModel):
    """Request schema for geocoding endpoint (used with local LLM mode)"""
    location_names: List[str] = Field(..., description="List of location names to geocode")


class GeocodeResponse(BaseModel):
    """Response schema for geocoding endpoint"""
    success: bool
    locations: List[LocationInfo] = []
    error: Optional[str] = None


class CreateContentRequest(BaseModel):
    source_url: str = Field(..., description="Source reel/post URL")


class ContentCard(BaseModel):
    id: str
    source_url: str
    source_platform: str
    status: str
    title_original: Optional[str] = None
    title_generated: Optional[str] = None
    summary_text: Optional[str] = None
    summary_method: Optional[str] = None
    thumbnail_url: Optional[str] = None
    likes_count: Optional[int] = None
    comments_count: Optional[int] = None
    views_count: Optional[int] = None
    semantic_tags: Optional[List[str]] = None
    mood_tags: Optional[List[str]] = None
    curator_insight: Optional[str] = None
    created_at: str
    updated_at: str


class ContentStatusResponse(BaseModel):
    success: bool
    content_id: str
    content_status: str
    job_status: Optional[str] = None
    stage: Optional[str] = None
    progress_percent: Optional[int] = None
    error: Optional[str] = None


class ExtractedMenuItem(BaseModel):
    id: str
    content_id: str
    location_id: Optional[str] = None
    name: str
    item_type: Optional[str] = None
    currency: Optional[str] = None
    price_value: Optional[float] = None
    price_display: Optional[str] = None
    price_confidence: Optional[float] = None


class MapPoint(BaseModel):
    content_id: str
    name: str
    display_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    geocoded: bool = True
    rating: Optional[float] = None
    review_count: Optional[int] = None
    place_category: Optional[str] = None
    image_url: Optional[str] = None


class MapLocationsResponse(BaseModel):
    success: bool
    points: List[MapPoint]
    count: int


class CreateContentResponse(BaseModel):
    success: bool
    content: ContentCard
    status: ContentStatusResponse
    menu_items: Optional[List[ExtractedMenuItem]] = None
    locations: Optional[List[MapPoint]] = None


class FeedResponse(BaseModel):
    success: bool
    items: List[ContentCard]
    count: int


class ActiveExtractionsResponse(BaseModel):
    """Phase 3 — in-flight content for the active extractions UI (queued/processing)."""

    success: bool
    items: List[ContentCard]
    count: int


class OperationResponse(BaseModel):
    """Generic success/failure envelope for cancel / admin ops."""

    success: bool
    message: str = ""


class BookmarkResponse(BaseModel):
    success: bool
    content_id: str


class Collection(BaseModel):
    id: str
    owner_user_id: str
    name: str
    description: Optional[str] = None
    cover_image_url: Optional[str] = None
    collection_type: str = "custom"
    created_at: str
    updated_at: str


class CreateCollectionRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    collection_type: str = "custom"
    cover_image_url: Optional[str] = None


class PatchCollectionRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    cover_image_url: Optional[str] = None


class CollectionsListResponse(BaseModel):
    success: bool
    items: List[Collection]
    count: int


class CollectionMutationResponse(BaseModel):
    success: bool
    collection: Collection


class AddCollectionItemRequest(BaseModel):
    content_id: str = Field(..., min_length=1)


class CollectionItemsResponse(BaseModel):
    success: bool
    items: List[ContentCard]
    count: int


class SearchResponse(BaseModel):
    success: bool
    items: List[ContentCard]
    count: int


class SuggestionsResponse(BaseModel):
    success: bool
    tags: List[str]
    titles: List[str]

