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


class LocationInfo(BaseModel):
    """Schema for location with coordinates"""
    name: str
    latitude: float
    longitude: float
    display_name: Optional[str] = None


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
    latitude: float
    longitude: float
    display_name: Optional[str] = None
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

