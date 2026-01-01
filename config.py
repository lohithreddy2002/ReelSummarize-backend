"""
Configuration settings for the ReelSummarize backend
"""
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

# Gemini model settings - use gemini-2.0-flash for video support
GEMINI_MODEL = "gemini-3-flash-preview"

# CORS settings - update with your app's URL in production
CORS_ORIGINS = [
    "*",  # Allow all origins for development
]

# =============================================================================
# PROMPTS CONFIGURATION
# =============================================================================

# System instruction for the AI summarizer
SYSTEM_INSTRUCTION = """You are a helpful assistant that summarizes social media video content (Instagram Reels, TikToks, etc.).
Your summaries should be:
- Concise and easy to read on mobile
- Informative and capture the key points
- Written in a friendly, engaging tone
- Formatted with clear structure"""

# Prompt for video-based summarization
VIDEO_SUMMARY_PROMPT = """
Please analyze the provided video and generate a report using the following defined sections. Ensure the formatting is optimized for mobile (short paragraphs and bullet points).

### 🏷️ Title:
Create a catchy, descriptive title (5-10 words) that captures the essence of this content. Make it engaging and informative. Just the title text, no quotes.

### 📝 Executive Summary
Provide a 2-3 sentence overview of the video's core purpose and narrative.

### 🔍 Key Topics & Themes
List the primary subjects or themes discussed using bullet points.

### 💡 Highlights & Takeaways
- **Products/Tools:** [Mention specific products and their key features]
- **Key Insights:** [List the most important takeaways or spoken points]
- **Notable Moments:** [Describe any specific scenes or events of interest]

### 📍 Locations:
List specific geographical locations, venues, cities, countries, or landmarks mentioned or shown in the video.
Format: One location per line, just the name (e.g., "Paris, France" or "Central Park, New York").
If no specific locations are identifiable, write exactly: "None mentioned"

---
**Constraint:** If the content is educational, focus on the "how-to." If it is entertainment, focus on the plot/action.
"""

# Prompt suffix for metadata-based summarization
METADATA_SUMMARY_PROMPT = """
Please provide:
1. A brief 2-3 sentence summary of what this content is about
2. Key topics or themes covered
3. Any notable highlights or takeaways

Keep the summary concise but informative. Format it nicely for mobile display."""

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

