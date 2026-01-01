"""
ReelSummarize Backend API
FastAPI server for downloading and summarizing Instagram reels
"""
import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

from config import HOST, PORT, CORS_ORIGINS, GEMINI_API_KEY, IS_VERCEL

# Configure logging for Vercel (stdout with immediate flush)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
from schemas import (
    SummarizeRequest,
    SummarizeResponse,
    HealthResponse,
    InfoRequest,
    InfoResponse,
    MediaInfo,
    LocationInfo,
    SearchLocationsRequest,
    SearchLocationsResponse,
    MatchedLocation,
)
from services.downloader import downloader, DownloadError
from services.summarizer import get_summarizer, SummarizationError, extract_title_from_summary, search_locations_with_ai
from services.geocoder import geocoder


# App version
VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    if IS_VERCEL:
        # Serverless: minimal startup, no persistent state
        logger.info("🚀 ReelSummarize Backend (Serverless)")
    else:
        logger.info("🚀 Starting ReelSummarize Backend...")
        logger.info(f"📡 Server running on http://{HOST}:{PORT}")
    logger.info(f"🔑 Gemini API: {'Configured' if GEMINI_API_KEY else 'NOT CONFIGURED'}")
    yield
    # Cleanup on shutdown (only for non-serverless)
    if not IS_VERCEL:
        logger.info("🧹 Cleaning up downloads...")
        downloader.cleanup_all()
        logger.info("👋 Shutting down...")


# Create FastAPI app
app = FastAPI(
    title="ReelSummarize API",
    description="API for downloading and summarizing Instagram reels and videos",
    version=VERSION,
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def cleanup_download(request_id: str):
    """Background task to cleanup downloaded files"""
    downloader.cleanup(request_id)


@app.get("/", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        version=VERSION,
        gemini_configured=bool(GEMINI_API_KEY),
    )


@app.get("/health", response_model=HealthResponse)
async def health():
    """Alias for health check"""
    return await health_check()


@app.post("/api/info", response_model=InfoResponse)
async def get_media_info(request: InfoRequest):
    """
    Get information about a media URL without downloading
    """
    try:
        info = await downloader.get_media_info(request.url)
        return InfoResponse(
            success=True,
            media_info=MediaInfo(
                id=info.get('id', ''),
                title=info.get('title'),
                description=info.get('description'),
                duration=info.get('duration'),
                uploader=info.get('uploader'),
                thumbnail=info.get('thumbnail'),
                platform=info.get('platform'),
            ),
        )
    except DownloadError as e:
        return InfoResponse(
            success=False,
            error=str(e),
        )
    except Exception as e:
        return InfoResponse(
            success=False,
            error=f"Unexpected error: {str(e)}",
        )


@app.post("/api/summarize", response_model=SummarizeResponse)
async def summarize_media(
    request: SummarizeRequest,
    background_tasks: BackgroundTasks,
):
    """
    Download media and generate a summary using Gemini AI
    
    This endpoint:
    1. Downloads the video/reel from the provided URL
    2. Uploads it to Gemini for analysis
    3. Returns an AI-generated summary
    
    The downloaded files are automatically cleaned up after processing.
    """
    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Gemini API is not configured. Please set GEMINI_API_KEY environment variable.",
        )
    
    request_id = None
    
    try:
        # Step 1: Download the media
        logger.info(f"📥 Downloading: {request.url}")
        download_info = await downloader.download_media(request.url)
        request_id = download_info.get('request_id')
        
        # Create media info object
        media_info = MediaInfo(
            id=download_info.get('id', ''),
            title=download_info.get('title'),
            description=download_info.get('description'),
            duration=download_info.get('duration'),
            uploader=download_info.get('uploader'),
            thumbnail=download_info.get('thumbnail'),
            platform=download_info.get('platform'),
        )
        
        # Step 2: Summarize the content
        logger.info("🤖 Generating summary...")
        summarizer = get_summarizer()
        
        result = await summarizer.summarize(
            video_path=download_info.get('file_path'),
            metadata=download_info,
            prefer_video=request.prefer_video_analysis,
        )
        
        # Step 3: Extract title and locations from summary
        locations_list = None
        generated_title = None
        summary_text = result.get('summary')
        
        if summary_text and result.get('success'):
            # Extract AI-generated title
            logger.info("🏷️ Extracting title from summary...")
            generated_title, _ = extract_title_from_summary(summary_text)
            if generated_title:
                logger.info(f"✅ Generated title: {generated_title}")
            
            # Extract locations and geocode them
            logger.info("📍 Extracting locations from summary...")
            location_names = geocoder.extract_locations_from_text(summary_text)
            
            if location_names:
                logger.info(f"📍 Found locations: {location_names}")
                geocoded = await geocoder.geocode_multiple(location_names)
                if geocoded:
                    locations_list = [
                        LocationInfo(
                            name=loc.name,
                            latitude=loc.latitude,
                            longitude=loc.longitude,
                            display_name=loc.display_name,
                        )
                        for loc in geocoded
                    ]
                    logger.info(f"✅ Geocoded {len(locations_list)} locations")
        
        # Schedule cleanup in background
        if request_id:
            background_tasks.add_task(cleanup_download, request_id)
        
        return SummarizeResponse(
            success=result.get('success', False),
            url=request.url,
            summary=result.get('summary'),
            generated_title=generated_title,
            method=result.get('method', 'failed'),
            media_info=media_info,
            locations=locations_list,
            error=result.get('error'),
        )
        
    except DownloadError as e:
        # Cleanup if download partially succeeded
        if request_id:
            background_tasks.add_task(cleanup_download, request_id)
        
        return SummarizeResponse(
            success=False,
            url=request.url,
            summary=None,
            method='failed',
            error=f"Download failed: {str(e)}",
        )
    
    except SummarizationError as e:
        if request_id:
            background_tasks.add_task(cleanup_download, request_id)
        
        return SummarizeResponse(
            success=False,
            url=request.url,
            summary=None,
            method='failed',
            error=f"Summarization failed: {str(e)}",
        )
    
    except Exception as e:
        if request_id:
            background_tasks.add_task(cleanup_download, request_id)
        
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}",
        )


@app.post("/api/summarize-quick", response_model=SummarizeResponse)
async def summarize_quick(request: SummarizeRequest):
    """
    Quick summarization using only metadata (no video download)
    
    This is faster but less accurate than full video analysis.
    Useful for getting a quick overview based on title/description.
    """
    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Gemini API is not configured. Please set GEMINI_API_KEY environment variable.",
        )
    
    try:
        # Get media info without downloading
        logger.info(f"📋 Fetching metadata: {request.url}")
        info = await downloader.get_media_info(request.url)
        
        media_info = MediaInfo(
            id=info.get('id', ''),
            title=info.get('title'),
            description=info.get('description'),
            duration=info.get('duration'),
            uploader=info.get('uploader'),
            thumbnail=info.get('thumbnail'),
            platform=info.get('platform'),
        )
        
        # Summarize from metadata only
        logger.info("🤖 Generating summary from metadata...")
        summarizer = get_summarizer()
        
        result = await summarizer.summarize(
            video_path=None,
            metadata=info,
            prefer_video=False,
        )
        
        # Extract title and locations from summary
        locations_list = None
        generated_title = None
        summary_text = result.get('summary')
        
        if summary_text and result.get('success'):
            # Extract AI-generated title
            logger.info("🏷️ Extracting title from summary...")
            generated_title, _ = extract_title_from_summary(summary_text)
            if generated_title:
                logger.info(f"✅ Generated title: {generated_title}")
            
            # Extract locations and geocode them
            logger.info("📍 Extracting locations from summary...")
            location_names = geocoder.extract_locations_from_text(summary_text)
            
            if location_names:
                logger.info(f"📍 Found locations: {location_names}")
                geocoded = await geocoder.geocode_multiple(location_names)
                if geocoded:
                    locations_list = [
                        LocationInfo(
                            name=loc.name,
                            latitude=loc.latitude,
                            longitude=loc.longitude,
                            display_name=loc.display_name,
                        )
                        for loc in geocoded
                    ]
                    logger.info(f"✅ Geocoded {len(locations_list)} locations")
        
        return SummarizeResponse(
            success=result.get('success', False),
            url=request.url,
            summary=result.get('summary'),
            generated_title=generated_title,
            method=result.get('method', 'failed'),
            media_info=media_info,
            locations=locations_list,
            error=result.get('error'),
        )
        
    except DownloadError as e:
        return SummarizeResponse(
            success=False,
            url=request.url,
            summary=None,
            generated_title=None,
            method='failed',
            error=f"Failed to fetch metadata: {str(e)}",
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}",
        )


@app.post("/api/search-locations", response_model=SearchLocationsResponse)
async def search_locations(request: SearchLocationsRequest):
    """
    Semantic search for locations across saved reels.
    
    Uses AI to match locations based on the user's query, considering
    the summary content and location context from each reel.
    """
    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Gemini API is not configured. Please set GEMINI_API_KEY environment variable.",
        )
    
    try:
        logger.info(f"🔍 Searching locations with query: '{request.query}'")
        logger.info(f"📚 Searching through {len(request.reels)} reels")
        
        # Convert reels to dict format for the search function
        reels_data = [
            {
                'id': reel.id,
                'url': reel.url,
                'title': reel.title,
                'summary': reel.summary,
                'locations': [
                    {
                        'name': loc.name,
                        'latitude': loc.latitude,
                        'longitude': loc.longitude,
                        'display_name': loc.display_name,
                    }
                    for loc in (reel.locations or [])
                ] if reel.locations else []
            }
            for reel in request.reels
        ]
        
        # Perform AI-powered search
        matched = await search_locations_with_ai(request.query, reels_data)
        
        # Convert to response format
        matched_locations = [
            MatchedLocation(
                name=loc['name'],
                latitude=loc['latitude'],
                longitude=loc['longitude'],
                display_name=loc.get('display_name'),
                source_url=loc['source_url'],
                source_title=loc.get('source_title'),
                reel_id=loc['reel_id'],
                relevance_reason=loc.get('relevance_reason'),
            )
            for loc in matched
        ]
        
        logger.info(f"✅ Found {len(matched_locations)} matching locations")
        
        return SearchLocationsResponse(
            success=True,
            query=request.query,
            matched_locations=matched_locations,
            total_matches=len(matched_locations),
        )
        
    except SummarizationError as e:
        logger.error(f"❌ Search failed: {e}")
        return SearchLocationsResponse(
            success=False,
            query=request.query,
            error=str(e),
        )
    except Exception as e:
        logger.error(f"❌ Unexpected error in search: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Search failed: {str(e)}",
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)

