# ReelSummarize Backend

A FastAPI backend service for downloading Instagram reels and generating AI-powered summaries using Google Gemini.

## Features

- 📥 Download Instagram reels and videos using yt-dlp
- 🤖 AI-powered video summarization using Google Gemini
- ⚡ Quick metadata-only summarization option
- 🧹 Automatic cleanup of downloaded files

## Setup

### 1. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create a `.env` file in the backend directory:

```bash
# Google Gemini API Key (required)
# Get your API key from: https://makersuite.google.com/app/apikey
GEMINI_API_KEY=your_gemini_api_key_here

# Server Configuration
HOST=0.0.0.0
PORT=8000

# Download Configuration
DOWNLOAD_DIR=./downloads
MAX_VIDEO_DURATION=300
```

### 3. Run the Server

```bash
# Development
python main.py

# Or with uvicorn directly
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## API Endpoints

### Health Check
```
GET /
GET /health
```
Returns server status and configuration info.

### Get Media Info
```
POST /api/info
{
    "url": "https://www.instagram.com/reel/..."
}
```
Returns metadata about a video without downloading.

### Full Summarization
```
POST /api/summarize
{
    "url": "https://www.instagram.com/reel/...",
    "prefer_video_analysis": true
}
```
Downloads the video and generates a comprehensive AI summary.

### Quick Summarization
```
POST /api/summarize-quick
{
    "url": "https://www.instagram.com/reel/..."
}
```
Generates a summary based on metadata only (faster but less detailed).

## Response Format

```json
{
    "success": true,
    "url": "https://www.instagram.com/reel/...",
    "summary": "This reel shows...",
    "method": "video_analysis",
    "media_info": {
        "id": "...",
        "title": "...",
        "description": "...",
        "duration": 30.5,
        "uploader": "...",
        "thumbnail": "...",
        "platform": "Instagram"
    },
    "error": null
}
```

## Notes

- Instagram may require authentication for some content. You can enable cookie-based auth in `services/downloader.py`.
- Video analysis provides more accurate summaries but takes longer.
- Downloaded files are automatically cleaned up after processing.

## First production deploy (Phase 1)

### 1. Supabase database

Apply SQL migrations in order (Supabase SQL editor or CLI):

1. `migrations/phase1_init.sql`
2. `migrations/phase1_enrichment_columns.sql`
3. `migrations/phase1_menu_items.sql`
4. `migrations/phase1_fts_indexes.sql`
5. `migrations/phase1_queue_lease.sql`
6. `migrations/phase2_collections.sql`
7. `migrations/phase2_search_documents.sql`
8. `migrations/phase2_map_detail_enrichment.sql`
9. `migrations/phase2_smart_views.sql` (optional reference views)
10. `migrations/phase2_model_response_json.sql`
11. `migrations/phase2_summary_prompt_json.sql`
12. `migrations/phase2_locations_geocoded.sql`

Create a Storage bucket (e.g. `media`) in Supabase Dashboard if you use `STORAGE_PROVIDER=supabase`.

Rollback (dev/staging only unless planned): `migrations/rollback_phase1.sql`

### 2. Environment variables

| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY` | Required for AI summarization |
| `MAPBOX_ACCESS_TOKEN` | Optional; geocoding (preferred over Google if set) |
| `GOOGLE_MAPS_API_KEY` | Optional; geocoding fallback |
| `YTDLP_COOKIES_FILE` | Optional; path to a Netscape-format cookies.txt for sites (e.g. Instagram) that block anonymous requests |
| `PERSISTENCE_PROVIDER` | `supabase` for production DB |
| `SUPABASE_URL` | Project URL |
| `SUPABASE_SECRET_KEY` | Server-only REST + storage |
| `AUTH_PROVIDER` | `supabase` with JWT, or `header` for dev |
| `SUPABASE_PUBLISHABLE_KEY` | Used by auth adapter when `AUTH_PROVIDER=supabase` |
| `STORAGE_PROVIDER` | `supabase` or `memory` (default) |
| `SUPABASE_STORAGE_BUCKET` | Bucket name (default `media`) |

### 3. Run

```bash
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Health: `GET /health` · Metrics: `GET /api/metrics` · Versioned aliases: `/api/v1/...`

