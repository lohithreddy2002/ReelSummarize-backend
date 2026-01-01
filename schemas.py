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

