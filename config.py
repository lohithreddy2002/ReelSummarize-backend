"""
Configuration settings for the ReelSummarize backend
"""
import base64
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Detect if running on Vercel (serverless)
IS_VERCEL = os.getenv("VERCEL", "0") == "1"

# Base directory
BASE_DIR = Path(__file__).resolve().parent

# API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
MAPBOX_ACCESS_TOKEN = os.getenv("MAPBOX_ACCESS_TOKEN", "")

# yt-dlp: path to a Netscape-format cookies.txt for sites (e.g. Instagram) that
# block anonymous requests. Export from a logged-in browser session.
# On serverless the repo is read-only, so instead set YTDLP_COOKIES_B64
# (base64 of the cookies.txt content) and it's decoded to /tmp on cold start.
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE", "")
_cookies_b64 = os.getenv("YTDLP_COOKIES_B64", "")
if _cookies_b64 and not YTDLP_COOKIES_FILE:
    _cookies_path = Path("/tmp/cookies.txt")
    try:
        _cookies_path.write_bytes(base64.b64decode(_cookies_b64))
        YTDLP_COOKIES_FILE = str(_cookies_path)
    except Exception:
        pass

# Server settings
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 7000))

# Download settings
# On Vercel, only /tmp is writable
if IS_VERCEL:
    DOWNLOAD_DIR = Path("/tmp/downloads")
else:
    DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", BASE_DIR / "downloads"))

MAX_VIDEO_DURATION = int(os.getenv("MAX_VIDEO_DURATION", 300))  # 5 minutes max

# Ensure download directory exists
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Gemini model — override via GEMINI_MODEL env var
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# CORS — comma-separated list of allowed origins, e.g.
#   CORS_ORIGINS=https://myapp.com,https://staging.myapp.com
# Defaults to "*" (all origins) only when the env var is absent or empty,
# which is acceptable in local dev but should be locked down in production.
_cors_raw = os.getenv("CORS_ORIGINS", "").strip()
CORS_ORIGINS = (
    [o.strip() for o in _cors_raw.split(",") if o.strip()]
    if _cors_raw
    else ["*"]
)

# -----------------------------------------------------------------------------
# Deploy (Supabase persistence/auth/storage)
# Set via environment / .env — never commit real keys.
# PERSISTENCE_PROVIDER=inmemory|supabase
# SUPABASE_URL=...
# SUPABASE_SECRET_KEY=...
# SUPABASE_PUBLISHABLE_KEY=...
# AUTH_PROVIDER=header|supabase
# AUTH_ALLOW_HEADER_FALLBACK=1|0
# STORAGE_PROVIDER=memory|supabase
# SUPABASE_STORAGE_BUCKET=media
# -----------------------------------------------------------------------------

# =============================================================================
# PROMPTS CONFIGURATION
# =============================================================================

# System instruction when the model sees the actual video file
SYSTEM_INSTRUCTION = """You are a helpful assistant that summarizes social media video content (Instagram Reels, TikToks, etc.).
Your summaries should be:
- Concise and easy to read on mobile
- Informative and capture the key points
- Written in a friendly, engaging tone
- Formatted with clear structure
You must carefully extract real-world place names from the video: read on-screen text, listen to speech, and use any location UI (stickers, maps, tags). Prefer concrete names over vague regions."""

# System instruction when only title/caption/hashtags/creator are available (no video)
METADATA_SYSTEM_INSTRUCTION = """You are a helpful assistant that summarizes social media posts from METADATA ONLY (you cannot see or hear the video).
Your summaries should be:
- Concise and easy to read on mobile
- Informative and grounded in the caption, @mentions, and hashtags
- Written in a friendly, engaging tone
- Formatted with clear structure
Extract place names ONLY from text in the metadata: caption, location tags, @mentions of venues, and hashtags. Prefer concrete, geocodable names (venue + area + city when stated). Do not claim you watched the video or heard audio."""

# Prompt for video-based summarization (structured JSON output)
VIDEO_SUMMARY_PROMPT = """
Analyze the provided video and return ONLY a valid JSON object (no markdown fences, no extra text).

Required JSON schema:
{
  "title": "string (5-12 words)",
  "summary_markdown": "string (mobile-friendly summary with short bullets/sections)",
  "semantic_tags": ["string", "..."],
  "mood_tags": ["string", "..."],
  "curator_insight": "string (1-2 concise recommendation sentences)",
  "locations": [
    {
      "name": "string (see PLACE NAMING below)",
      "place_category": "string|null",
      "rating": number|null,
      "review_count": integer|null,
      "image_url": "string|null"
    }
  ],
  "menu_items": [
    {
      "name": "string",
      "item_type": "string|null",
      "currency": "string|null",
      "price_value": number|null,
      "price_display": "string|null",
      "price_confidence": number|null
    }
  ]
}

=== PLACE NAMES IN THE VIDEO (highest priority) ===
Your job is to list every distinct real-world place that appears or is clearly named in the video. Scan the ENTIRE video, not only the first seconds.

1) VISUAL / ON-SCREEN (check every shot)
   - Text overlays, burned-in captions, subtitles, stickers, watermarks
   - Instagram/TikTok location stickers, "Add location" pills, map pins, Google Maps or Apple Maps snippets in frame
   - Storefront signs, neon signs, menus, receipts, delivery bags, branded cups (e.g. cafe/restaurant name)
   - Street signs, station names, airport codes, hotel names, mall names, neighborhood signs

2) SPOKEN AUDIO
   - Transcribe place names said out loud ("we're at …", "this is … in …", "heading to …")

3) CONTEXT FROM METADATA (if provided below)
   - Caption, description, hashtags — use them to disambiguate (e.g. turn "#connaughtplace" into "Connaught Place, New Delhi, India")

PLACE NAMING for `locations[].name`:
- Prefer the exact branded or official name as shown or said (e.g. "Blue Tokai Coffee, Khan Market, New Delhi").
- Then normalize to a geocodable string: "Venue or landmark, Area, City, Region/State, Country" when you can infer it.
- If you only have a landmark or venue, still output it; add city/country when the video or audio implies it.
- Output SEPARATE entries for distinct places (e.g. cafe A and park B = two objects).
- Do NOT use empty strings or generic-only names like "a restaurant", "the city", "somewhere in Europe". If truly no place is identifiable anywhere, use an empty `locations` array.

General rules:
- Use empty arrays for `locations` / `menu_items` only when nothing qualifies.
- Keep tags short (1-3 words).
- Ratings/reviews/image_url: only if clearly visible on screen (e.g. Google listing snippet); otherwise null.
- Do not invent prices, ratings, or places never hinted in video/audio/metadata.
"""

# User-message suffix for metadata-based summarization (structured JSON; schema aligned with video path)
METADATA_SUMMARY_PROMPT = """
=== TASK ===
You do NOT have the video. Use ONLY the post metadata in the message above.

Return ONLY a valid JSON object (no markdown code fences, no text before or after the JSON).

Required JSON schema (same keys as video analysis so the app can parse one shape):
{
  "title": "string (5-12 words; catchy, not the raw uploader default title alone)",
  "summary_markdown": "string (short sections or bullets; what the post is about)",
  "semantic_tags": ["string", "..."],
  "mood_tags": ["string", "..."],
  "curator_insight": "string (1-2 sentences; optional recommendation tone)",
  "locations": [
    {
      "name": "string (geocodable: venue or area, city, region/state, country when inferable)",
      "place_category": "string|null (e.g. cafe, restaurant — only if clearly implied)",
      "rating": null,
      "review_count": null,
      "image_url": null
    }
  ],
  "menu_items": [
    {
      "name": "string",
      "item_type": "string|null",
      "currency": null,
      "price_value": null,
      "price_display": "string|null (only if stated in caption)",
      "price_confidence": null
    }
  ]
}

Rules:
- Ground every claim in the caption, creator line, or hashtags. Do not invent visits, prices, or ratings.
- For places: use @mentions (e.g. @beyondbeancoffee), written addresses, neighborhood names (e.g. Brigade Road, Bengaluru), and hashtag clues. Merge duplicates into one `locations` entry with the best full name you can justify from text.
- Set `rating`, `review_count`, `image_url` to null in metadata-only mode unless the caption explicitly gives a number or URL.
- `menu_items`: only items clearly named in the caption (e.g. flavor names); otherwise [].
- Use [] for unknown lists; use null only where the schema allows.
"""

# System instruction for location search
SEARCH_SYSTEM_INSTRUCTION = """You are a helpful assistant that analyzes travel content and finds relevant locations. Always respond with valid JSON arrays only, no additional text."""

# Prompt template for semantic location search
# Use {query} and {reels_context} as placeholders
SEARCH_LOCATIONS_PROMPT = """You are helping a user search through their saved travel reels to find locations that match their query.

USER'S SEARCH QUERY: "{query}"

Here are the saved reels with their summaries and locations:

{reels_context}

Your task:
1. Analyze each reel's summary and locations
2. Determine which locations are relevant to the user's query "{query}"
3. A location is relevant if:
   - The summary mentions themes/activities related to the query
   - The location name suggests relevance (e.g., "Swiss Alps" for "winter destinations")
   - The content of the reel matches what the user is looking for

Return ONLY a JSON array of matching locations. For each match, include:
- reel_id: the ID of the reel
- location_name: the name of the matching location
- relevance_reason: a brief explanation (10-20 words) of why this matches the query

Example output format:
[
  {{"reel_id": "123", "location_name": "Swiss Alps", "relevance_reason": "Snow-covered mountains perfect for winter skiing and snowboarding adventures"}},
  {{"reel_id": "456", "location_name": "Aspen, Colorado", "relevance_reason": "Famous winter resort with excellent skiing conditions"}}
]

If no locations match the query, return an empty array: []

Important: Only include locations that genuinely match the search intent. Don't force matches."""

