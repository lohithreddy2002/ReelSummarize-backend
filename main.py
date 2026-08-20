"""
ReelSummarize Backend API
FastAPI server for downloading and summarizing Instagram reels
"""
import asyncio
import logging
import sys
import time
import uuid
from typing import Any
from contextlib import asynccontextmanager
from collections import defaultdict
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Header, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from config import HOST, PORT, CORS_ORIGINS, GEMINI_API_KEY, IS_VERCEL

# Configure logging — force=True so this works even when uvicorn has already
# added its own handlers to the root logger (basicConfig is a no-op otherwise).
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
logger = logging.getLogger(__name__)

# Paths to skip for per-request completion logs (high churn)
_LOG_SKIP_PATHS = frozenset(
    {
        "/",
        "/health",
        "/openapi.json",
        "/docs",
        "/redoc",
        "/docs/oauth2-redirect",
        "/favicon.ico",
    }
)


def api_log(request: Request | None, message: str, **fields: Any) -> None:
    """Structured API log line with optional request correlation id."""
    rid = getattr(request.state, "request_id", None) if request is not None else None
    if fields:
        parts = " ".join(f"{k}={v!r}" for k, v in fields.items())
        logger.info("[request_id=%s] %s %s", rid or "-", message, parts)
    else:
        logger.info("[request_id=%s] %s", rid or "-", message)
from domain.models import Collection as DomainCollection, Location as DomainLocation
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
    GeocodeRequest,
    GeocodeResponse,
    CreateContentRequest,
    CreateContentResponse,
    ContentCard,
    ContentStatusResponse,
    FeedResponse,
    MapPoint,
    MapLocationsResponse,
    BookmarkResponse,
    ExtractedMenuItem,
    Collection as CollectionSchema,
    CreateCollectionRequest,
    PatchCollectionRequest,
    CollectionsListResponse,
    CollectionMutationResponse,
    AddCollectionItemRequest,
    CollectionItemsResponse,
    SearchResponse,
    SuggestionsResponse,
    ActiveExtractionsResponse,
    OperationResponse,
)
from composition_root import get_persistence, get_auth
from application.content_service import ContentService
from application.collections_service import CollectionsService
from application.search_service import SearchService
from application.suggestions_service import SuggestionsService
from services.downloader import downloader, DownloadError
from services.summarizer import get_summarizer, SummarizationError, extract_title_from_summary, search_locations_with_ai
from services.geocoder import geocoder
from services.location_merge import merge_locations_for_content, locations_to_infos


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

content_service = ContentService(get_persistence())
collections_service = CollectionsService(get_persistence())
search_service = SearchService(get_persistence())
suggestions_service = SuggestionsService(get_persistence())
auth_port = get_auth()
request_metrics: dict[str, dict[str, list[float] | int]] = defaultdict(
    lambda: {"count": 0, "latencies_ms": [], "errors": 0}
)


def _to_content_card(item) -> ContentCard:
    return ContentCard(
        id=item.id,
        source_url=item.source_url,
        source_platform=item.source_platform,
        status=item.status,
        title_original=item.title_original,
        title_generated=item.title_generated,
        summary_text=item.summary_text,
        summary_method=item.summary_method,
        thumbnail_url=item.thumbnail_url,
        likes_count=item.likes_count,
        comments_count=item.comments_count,
        views_count=item.views_count,
        semantic_tags=item.semantic_tags,
        mood_tags=item.mood_tags,
        curator_insight=item.curator_insight,
        created_at=item.created_at.isoformat(),
        updated_at=item.updated_at.isoformat(),
    )


def _to_collection_schema(c: DomainCollection) -> CollectionSchema:
    return CollectionSchema(
        id=c.id,
        owner_user_id=c.owner_user_id,
        name=c.name,
        description=c.description,
        cover_image_url=c.cover_image_url,
        collection_type=c.collection_type,
        created_at=c.created_at.isoformat(),
        updated_at=c.updated_at.isoformat(),
    )


def _to_menu_item(item) -> ExtractedMenuItem:
    return ExtractedMenuItem(
        id=item.id,
        content_id=item.content_id,
        location_id=item.location_id,
        name=item.name,
        item_type=item.item_type,
        currency=item.currency,
        price_value=item.price_value,
        price_display=item.price_display,
        price_confidence=item.price_confidence,
    )


def _domain_location_to_map_point(loc: DomainLocation) -> MapPoint:
    return MapPoint(
        content_id=loc.content_id,
        name=loc.name,
        display_name=loc.display_name,
        latitude=loc.lat,
        longitude=loc.lng,
        geocoded=loc.geocoded,
        rating=loc.rating,
        review_count=loc.review_count,
        place_category=loc.place_category,
        image_url=loc.image_url,
    )


def cleanup_download(request_id: str):
    """Background task to cleanup downloaded files"""
    downloader.cleanup(request_id)


def _error_response(
    *,
    request_id: str,
    code: str,
    message: str,
    retryable: bool,
    status_code: int,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
                "request_id": request_id,
            },
        },
    )


# ponytail: per-instance in-memory limiter, resets on cold start / not shared
# across concurrent instances. Upgrade to a shared store (Supabase/Redis) if
# abuse survives instance churn.
_RATE_LIMITED_PATHS = frozenset({"/api/content", "/api/summarize", "/api/summarize-quick"})
_RATE_LIMIT_MAX = 10
_RATE_LIMIT_WINDOW_S = 60.0
_rate_limit_hits: dict[str, list[float]] = defaultdict(list)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path in _RATE_LIMITED_PATHS:
        key = request.headers.get("x-user-id") or (request.client.host if request.client else "unknown")
        now = time.monotonic()
        hits = _rate_limit_hits[key]
        cutoff = now - _RATE_LIMIT_WINDOW_S
        while hits and hits[0] < cutoff:
            hits.pop(0)
        if len(hits) >= _RATE_LIMIT_MAX:
            return _error_response(
                request_id=request.headers.get("x-request-id") or str(uuid.uuid4()),
                code="RATE_LIMITED",
                message="Too many requests. Please slow down and try again shortly.",
                retryable=True,
                status_code=429,
            )
        hits.append(now)
    return await call_next(request)


@app.middleware("http")
async def request_context_and_metrics_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.perf_counter() - start) * 1000
        bucket = request_metrics[request.url.path]
        bucket["count"] += 1
        bucket["errors"] += 1
        bucket["latencies_ms"].append(duration_ms)
        raise

    duration_ms = (time.perf_counter() - start) * 1000
    bucket = request_metrics[request.url.path]
    bucket["count"] += 1
    if response.status_code >= 400:
        bucket["errors"] += 1
    bucket["latencies_ms"].append(duration_ms)
    response.headers["x-request-id"] = request_id
    path = request.url.path
    if path not in _LOG_SKIP_PATHS and not path.startswith("/docs"):
        logger.info(
            "[request_id=%s] %s %s -> %s (%.2fms)",
            request_id,
            request.method,
            path,
            response.status_code,
            duration_ms,
        )
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    rid = getattr(request.state, "request_id", None)
    log_fn = logger.warning if exc.status_code < 500 else logger.error
    log_fn(
        "[request_id=%s] HTTPException %s %s: %s",
        rid or "-",
        request.method,
        request.url.path,
        exc.detail,
    )
    retryable = exc.status_code >= 500 or exc.status_code in (408, 429)
    return _error_response(
        request_id=getattr(request.state, "request_id", "unknown"),
        code=f"HTTP_{exc.status_code}",
        message=str(exc.detail),
        retryable=retryable,
        status_code=exc.status_code,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled server exception: %s", exc)
    return _error_response(
        request_id=getattr(request.state, "request_id", "unknown"),
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred",
        retryable=True,
        status_code=500,
    )


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
async def get_media_info(req: Request, request: InfoRequest):
    """
    Get information about a media URL without downloading
    """
    api_log(req, "api.info", url=request.url[:200] if request.url else "")
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
                video_url=info.get('video_url'),
            ),
        )
    except DownloadError as e:
        api_log(req, "api.info failed", error=str(e)[:200])
        return InfoResponse(
            success=False,
            error=str(e),
        )
    except Exception as e:
        api_log(req, "api.info error", error=str(e)[:200])
        return InfoResponse(
            success=False,
            error=f"Unexpected error: {str(e)}",
        )


@app.post("/api/summarize", response_model=SummarizeResponse)
async def summarize_media(
    request: SummarizeRequest,
    background_tasks: BackgroundTasks,
    req: Request,
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

    api_log(
        req,
        "api.summarize",
        url=str(request.url)[:200],
        prefer_video=request.prefer_video_analysis,
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
        
        # Step 3: Extract title and locations
        locations_list = None
        generated_title = result.get('title')
        summary_text = result.get('summary')

        if summary_text and result.get('success'):
            if not generated_title:
                logger.info("🏷️ Extracting title from summary...")
                generated_title, _ = extract_title_from_summary(summary_text)
            if generated_title:
                logger.info(f"✅ Generated title: {generated_title}")

            logger.info("📍 Extracting locations from summary...")
            structured_locations = result.get('locations') or []
            location_names = [
                str(x.get('name', '')).strip()
                for x in structured_locations
                if isinstance(x, dict)
            ]
            location_names = [x for x in location_names if x]
            if not location_names:
                location_names = geocoder.extract_locations_from_text(summary_text)

            if location_names:
                logger.info(f"📍 Found locations: {location_names}")
                merged = await merge_locations_for_content(
                    "", location_names, structured_locations, geocoder_svc=geocoder
                )
                locations_list = locations_to_infos(merged)
                n_ok = sum(1 for x in locations_list if x.geocoded)
                logger.info(f"📍 Resolved {len(locations_list)} locations ({n_ok} geocoded)")

        # Schedule cleanup in background
        if request_id:
            background_tasks.add_task(cleanup_download, request_id)

        api_log(
            req,
            "api.summarize done",
            success=result.get("success", False),
            method=result.get("method", "failed"),
        )

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

        api_log(req, "api.summarize download_failed", error=str(e)[:200])

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

        api_log(req, "api.summarize summarization_failed", error=str(e)[:200])

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

        api_log(req, "api.summarize unexpected_error", error=str(e)[:200])

        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}",
        )


@app.post("/api/summarize-quick", response_model=SummarizeResponse)
async def summarize_quick(request: SummarizeRequest, req: Request):
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

    api_log(req, "api.summarize_quick", url=str(request.url)[:200])

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
        generated_title = result.get('title')
        summary_text = result.get('summary')

        if summary_text and result.get('success'):
            if not generated_title:
                logger.info("🏷️ Extracting title from summary...")
                generated_title, _ = extract_title_from_summary(summary_text)
            if generated_title:
                logger.info(f"✅ Generated title: {generated_title}")

            logger.info("📍 Extracting locations from summary...")
            structured_locations = result.get('locations') or []
            location_names = [
                str(x.get('name', '')).strip()
                for x in structured_locations
                if isinstance(x, dict)
            ]
            location_names = [x for x in location_names if x]
            if not location_names:
                location_names = geocoder.extract_locations_from_text(summary_text)

            if location_names:
                logger.info(f"📍 Found locations: {location_names}")
                merged = await merge_locations_for_content(
                    "", location_names, structured_locations, geocoder_svc=geocoder
                )
                locations_list = locations_to_infos(merged)
                n_ok = sum(1 for x in locations_list if x.geocoded)
                logger.info(f"📍 Resolved {len(locations_list)} locations ({n_ok} geocoded)")

        api_log(
            req,
            "api.summarize_quick done",
            success=result.get("success", False),
            method=result.get("method", "failed"),
        )

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
        api_log(req, "api.summarize_quick metadata_failed", error=str(e)[:200])
        return SummarizeResponse(
            success=False,
            url=request.url,
            summary=None,
            generated_title=None,
            method='failed',
            error=f"Failed to fetch metadata: {str(e)}",
        )
    
    except Exception as e:
        api_log(req, "api.summarize_quick unexpected_error", error=str(e)[:200])
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}",
        )


@app.post("/api/geocode", response_model=GeocodeResponse)
async def geocode_locations(req: Request, request: GeocodeRequest):
    """
    Geocode a list of location names to get coordinates.
    
    This endpoint is used by clients running local VLM models
    to geocode locations extracted from locally-generated summaries.
    Only this endpoint and health checks should be called when using local models.
    """
    api_log(req, "api.geocode", count=len(request.location_names))
    try:
        logger.info(f"📍 Geocoding {len(request.location_names)} locations")
        
        merged = await merge_locations_for_content(
            "", request.location_names, [], geocoder_svc=geocoder
        )
        locations_list = locations_to_infos(merged)

        logger.info(
            f"✅ Geocode request: {len(locations_list)} locations "
            f"({sum(1 for x in locations_list if x.geocoded)} with coordinates)"
        )
        
        return GeocodeResponse(
            success=True,
            locations=locations_list,
        )
        
    except Exception as e:
        logger.error(f"❌ Geocoding error: {e}")
        api_log(req, "api.geocode error", error=str(e)[:200])
        return GeocodeResponse(
            success=False,
            error=str(e),
        )


@app.post("/api/search-locations", response_model=SearchLocationsResponse)
async def search_locations(req: Request, request: SearchLocationsRequest):
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

    api_log(
        req,
        "api.search_locations",
        query=request.query[:120] if request.query else "",
        reels=len(request.reels),
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
                        'geocoded': loc.geocoded,
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
                latitude=loc.get('latitude'),
                longitude=loc.get('longitude'),
                display_name=loc.get('display_name'),
                geocoded=loc.get(
                    'geocoded',
                    loc.get('latitude') is not None and loc.get('longitude') is not None,
                ),
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


@app.post("/api/content", response_model=CreateContentResponse)
async def create_content(
    req: Request,
    request: CreateContentRequest,
    x_user_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    auth_context = await auth_port.resolve_context(authorization=authorization, x_user_id=x_user_id)
    owner_user_id = auth_context.user_id
    api_log(
        req,
        "api.content.create",
        owner_user_id=owner_user_id,
        source_url=str(request.source_url)[:200],
    )
    created = await content_service.ingest_content(owner_user_id=owner_user_id, source_url=request.source_url)
    content = created["content"]

    try:
        await content_service.enrich_content_now(owner_user_id=owner_user_id, content_id=content.id)
    except Exception as exc:
        logger.warning(f"Enrichment failed for {content.id}: {exc}")

    latest = await content_service.get_status(owner_user_id=owner_user_id, content_id=content.id)
    if latest:
        content = latest["content"]
        job = latest["job"]
    else:
        job = created["job"]

    api_log(
        req,
        "api.content.create done",
        content_id=content.id,
        status=content.status,
        job_status=job.status if job else None,
    )

    menu = await content_service.persistence.list_menu_items(content.id, owner_user_id)
    menu_payload = [_to_menu_item(m) for m in menu] if menu else None
    locs = await content_service.get_locations_for_content(owner_user_id, content.id)
    locations_payload = [_domain_location_to_map_point(loc) for loc in locs] if locs else None

    return CreateContentResponse(
        success=True,
        content=_to_content_card(content),
        status=ContentStatusResponse(
            success=True,
            content_id=content.id,
            content_status=content.status,
            job_status=job.status,
            stage=job.stage,
            progress_percent=job.progress_percent,
        ),
        menu_items=menu_payload,
        locations=locations_payload,
    )


@app.get("/api/content/{content_id}", response_model=CreateContentResponse)
async def get_content_detail(
    req: Request,
    content_id: str,
    x_user_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    auth_context = await auth_port.resolve_context(authorization=authorization, x_user_id=x_user_id)
    owner_user_id = auth_context.user_id
    api_log(req, "api.content.detail", content_id=content_id, owner_user_id=owner_user_id)
    status_data = await content_service.get_status(owner_user_id=owner_user_id, content_id=content_id)
    if not status_data:
        raise HTTPException(status_code=404, detail="Content not found")
    content = status_data["content"]
    job = status_data["job"]
    menu = await content_service.persistence.list_menu_items(content_id, owner_user_id)
    menu_payload = [_to_menu_item(m) for m in menu] if menu else None
    locs = await content_service.get_locations_for_content(owner_user_id, content_id)
    locations_payload = [_domain_location_to_map_point(loc) for loc in locs] if locs else None
    return CreateContentResponse(
        success=True,
        content=_to_content_card(content),
        status=ContentStatusResponse(
            success=True,
            content_id=content.id,
            content_status=content.status,
            job_status=job.status if job else None,
            stage=job.stage if job else None,
            progress_percent=job.progress_percent if job else None,
        ),
        menu_items=menu_payload,
        locations=locations_payload,
    )


@app.get("/api/content/{content_id}/status", response_model=ContentStatusResponse)
async def get_content_status(
    req: Request,
    content_id: str,
    x_user_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    auth_context = await auth_port.resolve_context(authorization=authorization, x_user_id=x_user_id)
    owner_user_id = auth_context.user_id
    api_log(req, "api.content.status", content_id=content_id, owner_user_id=owner_user_id)
    status_data = await content_service.get_status(owner_user_id=owner_user_id, content_id=content_id)
    if not status_data:
        return ContentStatusResponse(
            success=False,
            content_id=content_id,
            content_status="not_found",
            error="Content not found",
        )
    content = status_data["content"]
    job = status_data["job"]
    return ContentStatusResponse(
        success=True,
        content_id=content.id,
        content_status=content.status,
        job_status=job.status if job else None,
        stage=job.stage if job else None,
        progress_percent=job.progress_percent if job else None,
        error=job.error_message if job else None,
    )


@app.get("/api/feed", response_model=FeedResponse)
async def get_feed(
    req: Request,
    x_user_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    auth_context = await auth_port.resolve_context(authorization=authorization, x_user_id=x_user_id)
    owner_user_id = auth_context.user_id
    api_log(req, "api.feed", owner_user_id=owner_user_id, limit=limit, offset=offset)
    rows = await content_service.get_feed(owner_user_id=owner_user_id, limit=limit, offset=offset)
    items = [_to_content_card(x) for x in rows]
    return FeedResponse(success=True, items=items, count=len(items))


@app.get("/api/extractions/active", response_model=ActiveExtractionsResponse)
async def get_active_extractions(
    req: Request,
    x_user_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    limit: int = Query(default=50, ge=1, le=100),
):
    auth_context = await auth_port.resolve_context(authorization=authorization, x_user_id=x_user_id)
    owner_user_id = auth_context.user_id
    api_log(req, "api.extractions.active", owner_user_id=owner_user_id, limit=limit)
    rows = await content_service.list_active_extractions(owner_user_id, limit=limit)
    items = [_to_content_card(x) for x in rows]
    return ActiveExtractionsResponse(success=True, items=items, count=len(items))


@app.get("/api/map/locations", response_model=MapLocationsResponse)
async def get_map_locations(
    req: Request,
    x_user_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    auth_context = await auth_port.resolve_context(authorization=authorization, x_user_id=x_user_id)
    owner_user_id = auth_context.user_id
    api_log(req, "api.map.locations", owner_user_id=owner_user_id)
    rows = await content_service.get_map_locations(owner_user_id=owner_user_id)
    points = [
        MapPoint(
            content_id=x.content_id,
            name=x.name,
            display_name=x.display_name,
            latitude=x.lat,
            longitude=x.lng,
            geocoded=x.geocoded,
            rating=x.rating,
            review_count=x.review_count,
            place_category=x.place_category,
            image_url=x.image_url,
        )
        for x in rows
    ]
    return MapLocationsResponse(success=True, points=points, count=len(points))


@app.post("/api/content/{content_id}/bookmark", response_model=BookmarkResponse)
async def bookmark_content(
    req: Request,
    content_id: str,
    x_user_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    auth_context = await auth_port.resolve_context(authorization=authorization, x_user_id=x_user_id)
    owner_user_id = auth_context.user_id
    api_log(req, "api.content.bookmark", content_id=content_id, owner_user_id=owner_user_id)
    ok = await content_service.bookmark(owner_user_id=owner_user_id, content_id=content_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Content not found")
    return BookmarkResponse(success=True, content_id=content_id)


@app.post("/api/content/{content_id}/cancel", response_model=OperationResponse)
async def cancel_content_extraction(
    req: Request,
    content_id: str,
    x_user_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    auth_context = await auth_port.resolve_context(authorization=authorization, x_user_id=x_user_id)
    owner_user_id = auth_context.user_id
    api_log(req, "api.content.cancel", content_id=content_id, owner_user_id=owner_user_id)
    ok = await content_service.cancel_extraction(owner_user_id=owner_user_id, content_id=content_id)
    if not ok:
        return OperationResponse(success=False, message="Nothing to cancel (not found or not active)")
    return OperationResponse(success=True, message="Extraction cancelled")


@app.delete("/api/content/{content_id}", response_model=OperationResponse)
async def delete_content(
    req: Request,
    content_id: str,
    x_user_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    auth_context = await auth_port.resolve_context(authorization=authorization, x_user_id=x_user_id)
    owner_user_id = auth_context.user_id
    api_log(req, "api.content.delete", content_id=content_id, owner_user_id=owner_user_id)
    ok = await content_service.delete_content(owner_user_id=owner_user_id, content_id=content_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Content not found")
    return OperationResponse(success=True, message="Content deleted")


@app.get("/api/collections", response_model=CollectionsListResponse)
async def list_collections(
    req: Request,
    x_user_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    auth_context = await auth_port.resolve_context(authorization=authorization, x_user_id=x_user_id)
    owner_user_id = auth_context.user_id
    api_log(req, "api.collections.list", owner_user_id=owner_user_id, limit=limit, offset=offset)
    rows = await collections_service.list_collections(owner_user_id, limit, offset)
    items = [_to_collection_schema(x) for x in rows]
    return CollectionsListResponse(success=True, items=items, count=len(items))


@app.post("/api/collections", response_model=CollectionMutationResponse)
async def create_collection(
    req: Request,
    body: CreateCollectionRequest,
    x_user_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    auth_context = await auth_port.resolve_context(authorization=authorization, x_user_id=x_user_id)
    owner_user_id = auth_context.user_id
    api_log(req, "api.collections.create", owner_user_id=owner_user_id, name=body.name[:80])
    c = await collections_service.create_collection(
        owner_user_id,
        body.name,
        body.description,
        body.collection_type,
        body.cover_image_url,
    )
    return CollectionMutationResponse(success=True, collection=_to_collection_schema(c))


@app.patch("/api/collections/{collection_id}", response_model=CollectionMutationResponse)
async def patch_collection(
    req: Request,
    collection_id: str,
    body: PatchCollectionRequest,
    x_user_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    auth_context = await auth_port.resolve_context(authorization=authorization, x_user_id=x_user_id)
    owner_user_id = auth_context.user_id
    api_log(req, "api.collections.patch", collection_id=collection_id, owner_user_id=owner_user_id)
    c = await collections_service.update_collection(
        owner_user_id,
        collection_id,
        name=body.name,
        description=body.description,
        cover_image_url=body.cover_image_url,
    )
    if not c:
        raise HTTPException(status_code=404, detail="Collection not found")
    return CollectionMutationResponse(success=True, collection=_to_collection_schema(c))


@app.delete("/api/collections/{collection_id}")
async def delete_collection(
    req: Request,
    collection_id: str,
    x_user_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    auth_context = await auth_port.resolve_context(authorization=authorization, x_user_id=x_user_id)
    owner_user_id = auth_context.user_id
    api_log(req, "api.collections.delete", collection_id=collection_id, owner_user_id=owner_user_id)
    ok = await collections_service.delete_collection(owner_user_id, collection_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Collection not found")
    return {"success": True}


@app.post("/api/collections/{collection_id}/items")
async def add_collection_item(
    req: Request,
    collection_id: str,
    body: AddCollectionItemRequest,
    x_user_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    auth_context = await auth_port.resolve_context(authorization=authorization, x_user_id=x_user_id)
    owner_user_id = auth_context.user_id
    api_log(
        req,
        "api.collections.items.add",
        collection_id=collection_id,
        content_id=body.content_id,
        owner_user_id=owner_user_id,
    )
    try:
        await collections_service.add_item(owner_user_id, collection_id, body.content_id)
    except ValueError as e:
        if str(e) == "collection_not_found":
            raise HTTPException(status_code=404, detail="Collection not found")
        if str(e) == "content_not_found":
            raise HTTPException(status_code=404, detail="Content not found")
        raise
    return {"success": True, "content_id": body.content_id}


@app.delete("/api/collections/{collection_id}/items/{content_id}")
async def remove_collection_item(
    req: Request,
    collection_id: str,
    content_id: str,
    x_user_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    auth_context = await auth_port.resolve_context(authorization=authorization, x_user_id=x_user_id)
    owner_user_id = auth_context.user_id
    api_log(
        req,
        "api.collections.items.remove",
        collection_id=collection_id,
        content_id=content_id,
        owner_user_id=owner_user_id,
    )
    try:
        await collections_service.remove_item(owner_user_id, collection_id, content_id)
    except ValueError as e:
        if str(e) == "collection_not_found":
            raise HTTPException(status_code=404, detail="Collection not found")
        raise
    return {"success": True}


@app.get("/api/collections/{collection_id}/items", response_model=CollectionItemsResponse)
async def list_collection_items(
    req: Request,
    collection_id: str,
    x_user_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    auth_context = await auth_port.resolve_context(authorization=authorization, x_user_id=x_user_id)
    owner_user_id = auth_context.user_id
    api_log(req, "api.collections.items.list", collection_id=collection_id, owner_user_id=owner_user_id)
    rows = await collections_service.list_items(owner_user_id, collection_id, limit, offset)
    items = [_to_content_card(x) for x in rows]
    return CollectionItemsResponse(success=True, items=items, count=len(items))


@app.get("/api/search", response_model=SearchResponse)
async def unified_search(
    req: Request,
    x_user_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    q: str | None = Query(default=None),
    smart: str | None = Query(
        default=None,
        description="Optional: to_visit, recent, reels, posts",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    auth_context = await auth_port.resolve_context(authorization=authorization, x_user_id=x_user_id)
    owner_user_id = auth_context.user_id
    api_log(req, "api.search", owner_user_id=owner_user_id, q=(q or "")[:80], smart=smart)
    rows = await search_service.search_items(
        owner_user_id, q=q, smart=smart, limit=limit, offset=offset
    )
    items = [_to_content_card(x) for x in rows]
    return SearchResponse(success=True, items=items, count=len(items))


@app.get("/api/suggestions", response_model=SuggestionsResponse)
async def get_suggestions(
    req: Request,
    x_user_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    q: str | None = Query(default=None),
):
    auth_context = await auth_port.resolve_context(authorization=authorization, x_user_id=x_user_id)
    owner_user_id = auth_context.user_id
    api_log(req, "api.suggestions", owner_user_id=owner_user_id, q=(q or "")[:80])
    data = await suggestions_service.suggestions(owner_user_id, q)
    return SuggestionsResponse(success=data["success"], tags=data["tags"], titles=data["titles"])


@app.get("/api/metrics")
async def get_metrics(req: Request):
    api_log(req, "api.metrics")
    out = {}
    for path, item in request_metrics.items():
        latencies = sorted(item["latencies_ms"])
        p50 = latencies[int(0.5 * (len(latencies) - 1))] if latencies else 0.0
        p95 = latencies[int(0.95 * (len(latencies) - 1))] if latencies else 0.0
        count = int(item["count"])
        errors = int(item["errors"])
        error_rate = (errors / count) if count else 0.0
        out[path] = {
            "request_count": count,
            "latency_p50_ms": round(p50, 2),
            "latency_p95_ms": round(p95, 2),
            "error_rate": round(error_rate, 4),
        }
    return {"success": True, "metrics": out}


def _register_v1_aliases() -> None:
    """
    Strategy for API versioning: expose /api/v1/* aliases for /api/* routes.
    """
    for route in list(app.routes):
        path = getattr(route, "path", "")
        if not path.startswith("/api/") or path.startswith("/api/v1/"):
            continue
        methods = sorted(m for m in (getattr(route, "methods", set()) or set()) if m not in {"HEAD", "OPTIONS"})
        if not methods:
            continue
        alias = "/api/v1" + path[len("/api") :]
        app.add_api_route(
            alias,
            route.endpoint,
            methods=methods,
            include_in_schema=False,
        )


_register_v1_aliases()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)

