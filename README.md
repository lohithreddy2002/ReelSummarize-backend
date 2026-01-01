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

