"""
ReelSummarize Backend API
FastAPI server for downloading and summarizing Instagram reels
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

from config import HOST, PORT, CORS_ORIGINS, GEMINI_API_KEY, IS_VERCEL
from schemas import (
    SummarizeRequest,
    SummarizeResponse,
    HealthResponse,
    InfoRequest,
    InfoResponse,
    MediaInfo,
    LocationInfo,
)
from services.downloader import downloader, DownloadError
from services.summarizer import get_summarizer, SummarizationError, extract_title_from_summary
from services.geocoder import geocoder


# App version
VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    if IS_VERCEL:
        # Serverless: minimal startup, no persistent state
        print("🚀 ReelSummarize Backend (Serverless)")
    else:
        print("🚀 Starting ReelSummarize Backend...")
        print(f"📡 Server running on http://{HOST}:{PORT}")
    print(f"🔑 Gemini API: {'Configured' if GEMINI_API_KEY else 'NOT CONFIGURED'}")
    yield
    # Cleanup on shutdown (only for non-serverless)
    if not IS_VERCEL:
        print("🧹 Cleaning up downloads...")
        downloader.cleanup_all()
        print("👋 Shutting down...")


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
        print(f"📥 Downloading: {request.url}")
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
        print(f"🤖 Generating summary...")
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
            print(f"🏷️ Extracting title from summary...")
            generated_title, _ = extract_title_from_summary(summary_text)
            if generated_title:
                print(f"✅ Generated title: {generated_title}")
            
            # Extract locations and geocode them
            print(f"📍 Extracting locations from summary...")
            location_names = geocoder.extract_locations_from_text(summary_text)
            
            if location_names:
                print(f"📍 Found locations: {location_names}")
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
                    print(f"✅ Geocoded {len(locations_list)} locations")
        
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
        print(f"📋 Fetching metadata: {request.url}")
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
        print(f"🤖 Generating summary from metadata...")
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
            print(f"🏷️ Extracting title from summary...")
            generated_title, _ = extract_title_from_summary(summary_text)
            if generated_title:
                print(f"✅ Generated title: {generated_title}")
            
            # Extract locations and geocode them
            print(f"📍 Extracting locations from summary...")
            location_names = geocoder.extract_locations_from_text(summary_text)
            
            if location_names:
                print(f"📍 Found locations: {location_names}")
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
                    print(f"✅ Geocoded {len(locations_list)} locations")
        
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)

