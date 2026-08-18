"""
Summarization service using Google Gemini API (google-genai package)
"""
import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

logger = logging.getLogger(__name__)

from google import genai
from google.genai import types

from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    SYSTEM_INSTRUCTION,
    METADATA_SYSTEM_INSTRUCTION,
    VIDEO_SUMMARY_PROMPT,
    METADATA_SUMMARY_PROMPT,
    SEARCH_SYSTEM_INSTRUCTION,
    SEARCH_LOCATIONS_PROMPT,
)


class SummarizationError(Exception):
    """Custom exception for summarization errors"""
    pass


def extract_title_from_summary(summary: str) -> Tuple[Optional[str], str]:
    """
    Extract the generated title from the summary text.
    Returns a tuple of (title, summary_without_title_section).
    """
    if not summary:
        return None, summary
    
    # Patterns to match title section
    patterns = [
        # ### 🏷️ Title: or ### Title:
        r"#{1,4}\s*🏷️?\s*Title\s*:?\s*\n+(.+?)(?=\n#{1,4}\s|\n\n|$)",
        # **Title:** format
        r"\*\*\s*🏷️?\s*Title\s*:?\s*\*\*\s*\n?(.+?)(?=\n#{1,4}|\n\*\*|\n\n|$)",
        # Simple Title: format at start
        r"^🏷️?\s*Title\s*:?\s*\n?(.+?)(?=\n#{1,4}|\n\n|$)",
    ]
    
    title = None
    for pattern in patterns:
        match = re.search(pattern, summary, re.IGNORECASE | re.MULTILINE)
        if match:
            title = match.group(1).strip()
            # Clean up the title
            title = title.strip('"\'""''')  # Remove quotes
            title = title.strip('.')  # Remove trailing period
            title = ' '.join(title.split())  # Normalize whitespace
            
            # Validate title (should be reasonable length)
            if 3 <= len(title) <= 150:
                break
            else:
                title = None
    
    return title, summary


def _strip_json_fences(text: str) -> str:
    v = (text or '').strip()
    if v.startswith('```'):
        lines = v.splitlines()
        if lines and lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        v = '\n'.join(lines).strip()
    return v


def _safe_float(v: Any) -> float | None:
    try:
        if v is None or v == '':
            return None
        return float(v)
    except Exception:
        return None


def _safe_int(v: Any) -> int | None:
    try:
        if v is None or v == '':
            return None
        return int(v)
    except Exception:
        return None


def _clean_tag_list(v: Any, max_items: int = 12) -> list[str]:
    if not isinstance(v, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in v:
        t = str(item).strip().lower()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t[:40])
        if len(out) >= max_items:
            break
    return out


def _normalize_ingest_caption(description: str) -> str:
    """
    yt-dlp / Instagram often returns description with redundant 'Caption' / 'Description:' lines.
    Strip those so we do not double-label in the model prompt.
    """
    s = (description or "").strip()
    if not s:
        return ""
    s = re.sub(r"^Caption\s*\n+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^Description:\s*", "", s, flags=re.IGNORECASE)
    return s.strip()


def parse_structured_summary(raw_text: str) -> Dict[str, Any]:
    cleaned = _strip_json_fences(raw_text)
    try:
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError('summary json is not object')
    except Exception:
        # fallback for legacy markdown/plain text
        title, summary = extract_title_from_summary(raw_text or '')
        return {
            'summary_markdown': summary or raw_text or '',
            'title': title,
            'semantic_tags': [],
            'mood_tags': [],
            'curator_insight': None,
            'locations': [],
            'menu_items': [],
            'raw_text': raw_text or '',
            'structured': False,
        }

    summary = str(data.get('summary_markdown') or '').strip()
    title = str(data.get('title') or '').strip() or None
    locations: list[dict[str, Any]] = []
    for loc in (data.get('locations') or []):
        if not isinstance(loc, dict):
            continue
        name = str(loc.get('name') or '').strip()
        if not name:
            continue
        locations.append({
            'name': name,
            'place_category': (str(loc.get('place_category')).strip() if loc.get('place_category') is not None else None),
            'rating': _safe_float(loc.get('rating')),
            'review_count': _safe_int(loc.get('review_count')),
            'image_url': (str(loc.get('image_url')).strip() if loc.get('image_url') else None),
        })

    menu_items: list[dict[str, Any]] = []
    for row in (data.get('menu_items') or []):
        if not isinstance(row, dict):
            continue
        name = str(row.get('name') or '').strip()
        if not name:
            continue
        menu_items.append({
            'name': name,
            'item_type': (str(row.get('item_type')).strip() if row.get('item_type') is not None else None),
            'currency': (str(row.get('currency')).strip() if row.get('currency') is not None else None),
            'price_value': _safe_float(row.get('price_value')),
            'price_display': (str(row.get('price_display')).strip() if row.get('price_display') is not None else None),
            'price_confidence': _safe_float(row.get('price_confidence')),
        })

    return {
        'summary_markdown': summary,
        'title': title,
        'semantic_tags': _clean_tag_list(data.get('semantic_tags')),
        'mood_tags': _clean_tag_list(data.get('mood_tags')),
        'curator_insight': (str(data.get('curator_insight')).strip() if data.get('curator_insight') else None),
        'locations': locations,
        'menu_items': menu_items,
        'raw_text': raw_text or '',
        'structured': True,
    }



class Summarizer:
    """Service for summarizing video content using Gemini API"""
    
    def __init__(self):
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY environment variable is not set")
        
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.model = GEMINI_MODEL
    
    def _upload_file(self, file_path: str, mime_type: str = 'video/mp4') -> tuple[str, str]:
        """
        Uploads a local file to Google's File API.
        Returns a tuple of (file_uri, file_name)
        """
        if not Path(file_path).exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        file = self.client.files.upload(
            file=file_path,
            config=types.UploadFileConfig(
                mime_type=mime_type,
            ),
        )
        
        return file.uri, file.name
    
    def _wait_for_file_active(self, file_name: str, max_wait_seconds: int = 120) -> bool:
        """
        Wait for the uploaded file to become ACTIVE.
        Returns True if file is active, raises error if failed or timeout.
        """
        import time
        
        start_time = time.time()
        poll_interval = 2  # seconds
        
        while True:
            file = self.client.files.get(name=file_name)
            state = getattr(file.state, 'name', str(file.state)) if hasattr(file.state, 'name') else str(file.state)
            
            logger.debug("gemini file state: %s", state)

            if state == "ACTIVE":
                logger.info("gemini file is ACTIVE and ready for processing")
                return True
            elif state == "FAILED":
                raise SummarizationError(f"File processing failed on Google's servers")

            # Check timeout
            elapsed = time.time() - start_time
            if elapsed >= max_wait_seconds:
                raise SummarizationError(f"Timeout waiting for file to become active (waited {max_wait_seconds}s)")

            logger.debug("waiting for gemini file to be processed (%.0fs elapsed)", elapsed)
            time.sleep(poll_interval)
    
    def _delete_file(self, file_name: str) -> None:
        """Delete an uploaded file from Google's File API"""
        try:
            self.client.files.delete(name=file_name)
            logger.info("gemini uploaded file deleted: %s", file_name)
        except Exception as e:
            logger.warning("failed to delete gemini uploaded file %s: %s", file_name, e)
    
    def _create_summary_prompt(self, context: Dict[str, Any]) -> str:
        """Create a prompt for summarization based on available context (metadata-only path)."""
        raw_desc = str(context.get("description") or "")
        caption = _normalize_ingest_caption(raw_desc)

        prompt_parts: list[str] = [
            "=== POST METADATA (no video; caption and fields below are the only source) ===",
        ]

        title = str(context.get("title") or "").strip()
        if title:
            prompt_parts.append(f"Title (platform): {title}")

        if caption:
            prompt_parts.append("Caption:\n" + caption)

        uploader = str(context.get("uploader") or "").strip()
        if uploader:
            prompt_parts.append(f"Creator / uploader: {uploader}")

        if context.get("duration") is not None:
            duration = context["duration"]
            try:
                minutes = int(duration // 60)
                seconds = int(duration % 60)
                prompt_parts.append(f"Duration: {minutes}m {seconds}s")
            except (TypeError, ValueError):
                pass

        hashtags = self._extract_hashtags(raw_desc)
        if hashtags:
            prompt_parts.append(f"Hashtags (from caption): {', '.join(hashtags)}")

        prompt_parts.append("")
        prompt_parts.append(METADATA_SUMMARY_PROMPT.strip())

        return "\n".join(prompt_parts)

    @staticmethod
    def _extract_hashtags(text: Any, max_tags: int = 15) -> list[str]:
        raw = str(text or "")
        if not raw:
            return []
        tags = re.findall(r"#([A-Za-z0-9_]{2,40})", raw)
        out: list[str] = []
        seen: set[str] = set()
        for t in tags:
            norm = t.strip().lower()
            if not norm or norm in seen:
                continue
            seen.add(norm)
            out.append(f"#{norm}")
            if len(out) >= max_tags:
                break
        return out
    
    def _get_video_summary_prompt(self) -> str:
        """Get the video summary prompt from config"""
        return VIDEO_SUMMARY_PROMPT

    def _build_video_user_prompt(self, metadata: Optional[Dict[str, Any]]) -> str:
        """Full user text sent with the video (base prompt + optional metadata context)."""
        prompt = self._get_video_summary_prompt()
        if not metadata:
            return prompt
        context_parts = []
        if metadata.get("title"):
            context_parts.append(f"Title (platform): {metadata['title']}")
        if metadata.get("uploader"):
            context_parts.append(f"Creator / uploader: {metadata['uploader']}")
        raw_desc = str(metadata.get("description") or "")
        cap = _normalize_ingest_caption(raw_desc)
        if cap:
            context_parts.append("Caption:\n" + cap)
        if metadata.get("duration") is not None:
            try:
                duration = metadata["duration"]
                minutes = int(duration // 60)
                seconds = int(duration % 60)
                context_parts.append(f"Duration: {minutes}m {seconds}s")
            except (TypeError, ValueError):
                pass
        hashtags = self._extract_hashtags(raw_desc)
        if hashtags:
            context_parts.append(f"Hashtags (from caption): {', '.join(hashtags)}")
        if context_parts:
            prompt += "\n\n=== Additional context (same post; use with video) ===\n" + "\n".join(context_parts)
        return prompt

    def _summary_prompt_snapshot(
        self, *, user_prompt: str, system_instruction: str | None = None
    ) -> Dict[str, str]:
        return {
            "system_instruction": system_instruction or self._get_system_instruction(),
            "user_prompt": user_prompt,
        }

    def _get_system_instruction(self) -> str:
        """System instruction when the model analyzes video."""
        return SYSTEM_INSTRUCTION

    def _get_metadata_system_instruction(self) -> str:
        """System instruction for caption/metadata-only summarization."""
        return METADATA_SYSTEM_INSTRUCTION
    
    async def summarize_from_metadata(self, metadata: Dict[str, Any]) -> str:
        """
        Generate summary from metadata only (title, description, etc.)
        """
        def _generate():
            try:
                prompt = self._create_summary_prompt(metadata)
                
                contents = [
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=prompt)],
                    ),
                ]
                
                config = types.GenerateContentConfig(
                    system_instruction=[
                        types.Part.from_text(text=self._get_metadata_system_instruction()),
                    ],
                )

                response = self.client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=config,
                )

                return response.text
            except Exception as e:
                raise SummarizationError(f"Failed to generate summary: {str(e)}")

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _generate)

    async def summarize_video(self, video_path: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Generate summary by analyzing the actual video content.
        Always cleans up uploaded files, even if API call fails.
        """
        def _generate():
            file_name = None
            file_uri = None
            
            try:
                video_file = Path(video_path)
                if not video_file.exists():
                    raise SummarizationError(f"Video file not found: {video_path}")
                
                # Determine mime type
                suffix = video_file.suffix.lower()
                mime_types = {
                    '.mp4': 'video/mp4',
                    '.webm': 'video/webm',
                    '.mov': 'video/quicktime',
                    '.mkv': 'video/x-matroska',
                    '.avi': 'video/x-msvideo',
                }
                mime_type = mime_types.get(suffix, 'video/mp4')
                
                # Upload the video
                logger.info("uploading video to gemini: %s", video_path)
                try:
                    file_uri, file_name = self._upload_file(str(video_file), mime_type)
                    logger.info("gemini file uploaded: %s", file_uri)
                except Exception as upload_error:
                    logger.error("gemini file upload failed: %s", upload_error)
                    raise SummarizationError(f"Failed to upload video: {str(upload_error)}")

                # Wait for file to be processed and become ACTIVE
                logger.info("waiting for gemini file to become active")
                try:
                    self._wait_for_file_active(file_name)
                except SummarizationError:
                    raise
                except Exception as wait_error:
                    logger.error("error waiting for gemini file: %s", wait_error)
                    raise SummarizationError(f"Failed waiting for file processing: {str(wait_error)}")
                
                prompt = self._build_video_user_prompt(metadata)

                # Create content with video
                contents = [
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_uri(
                                file_uri=file_uri,
                                mime_type=mime_type,
                            ),
                        ],
                    ),
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=prompt)],
                    ),
                ]
                
                config = types.GenerateContentConfig(
                    system_instruction=[
                        types.Part.from_text(text=self._get_system_instruction()),
                    ],
                )
                
                # Generate content
                logger.info("calling gemini API for video summarization")
                try:
                    response = self.client.models.generate_content(
                        model=self.model,
                        contents=contents,
                        config=config,
                    )
                    logger.info("gemini API call successful")
                    return response.text
                except Exception as api_error:
                    logger.error("gemini API call failed: %s", api_error)
                    raise SummarizationError(f"Gemini API error: {str(api_error)}")

            except SummarizationError:
                raise
            except Exception as e:
                logger.error("unexpected error during video analysis: %s", e)
                raise SummarizationError(f"Failed to analyze video: {str(e)}")
            finally:
                # ALWAYS clean up the uploaded file, regardless of success or failure
                if file_name:
                    self._delete_file(file_name)
        
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _generate)
    
    async def summarize(
        self,
        video_path: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        prefer_video: bool = True
    ) -> Dict[str, Any]:
        """
        Main summarization method that chooses the best approach.
        Always returns gracefully, never raises exceptions.
        Uploaded files are always cleaned up even on failure.
        """
        video_error = None
        
        # Try video analysis first if available and preferred
        if video_path and prefer_video:
            try:
                summary = await self.summarize_video(video_path, metadata)
                structured = parse_structured_summary(summary)
                user_prompt = self._build_video_user_prompt(metadata)
                return {
                    'summary': structured.get('summary_markdown') or summary,
                    'title': structured.get('title'),
                    'semantic_tags': structured.get('semantic_tags', []),
                    'mood_tags': structured.get('mood_tags', []),
                    'curator_insight': structured.get('curator_insight'),
                    'locations': structured.get('locations', []),
                    'menu_items': structured.get('menu_items', []),
                    'structured': structured.get('structured', False),
                    'method': 'video_analysis',
                    'success': True,
                    "summary_prompt_json": self._summary_prompt_snapshot(user_prompt=user_prompt),
                }
            except SummarizationError as e:
                video_error = str(e)
                logger.warning("video analysis failed, falling back to metadata: %s", e)
            except Exception as e:
                video_error = str(e)
                logger.warning("unexpected error in video analysis, falling back to metadata: %s", e)
        
        # Fall back to metadata-based summarization
        if metadata and (metadata.get('title') or metadata.get('description')):
            try:
                summary = await self.summarize_from_metadata(metadata)
                structured = parse_structured_summary(summary)
                user_prompt = self._create_summary_prompt(metadata)
                return {
                    "summary": structured.get("summary_markdown") or summary,
                    "title": structured.get("title"),
                    "semantic_tags": structured.get("semantic_tags", []),
                    "mood_tags": structured.get("mood_tags", []),
                    "curator_insight": structured.get("curator_insight"),
                    "locations": structured.get("locations", []),
                    "menu_items": structured.get("menu_items", []),
                    "structured": structured.get("structured", False),
                    "method": "metadata_analysis",
                    "success": True,
                    "summary_prompt_json": self._summary_prompt_snapshot(
                        user_prompt=user_prompt,
                        system_instruction=self._get_metadata_system_instruction(),
                    ),
                }
            except SummarizationError as e:
                return {
                    'summary': None,
                    'method': 'failed',
                    'success': False,
                    'error': str(e),
                }
            except Exception as e:
                return {
                    'summary': None,
                    'method': 'failed',
                    'success': False,
                    'error': f"Unexpected error: {str(e)}",
                }
        
        # No video or metadata available, or both failed
        error_msg = video_error or 'No content available for summarization'
        return {
            'summary': None,
            'method': 'failed' if video_error else 'none',
            'success': False,
            'error': error_msg,
        }


# Create singleton instance (will be initialized when GEMINI_API_KEY is set)
summarizer: Optional[Summarizer] = None

def get_summarizer() -> Summarizer:
    """Get or create the summarizer instance"""
    global summarizer
    if summarizer is None:
        summarizer = Summarizer()
    return summarizer


async def search_locations_with_ai(
    query: str, 
    reels_data: list[dict]
) -> list[dict]:
    """
    Use Gemini AI to semantically search locations based on a query.
    
    Args:
        query: User's search query (e.g., "winter destinations", "beach vacation")
        reels_data: List of reels with their summaries and locations
        
    Returns:
        List of matched locations with relevance reasons
    """
    if not GEMINI_API_KEY:
        raise SummarizationError("Gemini API is not configured")
    
    # Build context for AI
    reels_context = []
    for reel in reels_data:
        if not reel.get('locations'):
            continue
        
        reel_info = {
            'id': reel.get('id', ''),
            'title': reel.get('title', 'Untitled'),
            'summary': reel.get('summary', ''),
            'url': reel.get('url', ''),
            'locations': [
                {
                    'name': loc.get('name', ''),
                    'latitude': loc.get('latitude'),
                    'longitude': loc.get('longitude'),
                    'display_name': loc.get('display_name', ''),
                    'geocoded': loc.get(
                        'geocoded',
                        loc.get('latitude') is not None and loc.get('longitude') is not None,
                    ),
                }
                for loc in reel.get('locations', [])
            ]
        }
        reels_context.append(reel_info)
    
    if not reels_context:
        return []
    
    # Create prompt for AI using config template
    search_prompt = SEARCH_LOCATIONS_PROMPT.format(
        query=query,
        reels_context=json.dumps(reels_context, indent=2),
    )

    def _search():
        try:
            client = get_summarizer().client  # reuse the singleton client
            contents = [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=search_prompt)],
                ),
            ]
            
            config = types.GenerateContentConfig(
                system_instruction=[
                    types.Part.from_text(text=SEARCH_SYSTEM_INSTRUCTION),
                ],
            )
            
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=config,
            )
            
            return response.text
        except Exception as e:
            raise SummarizationError(f"Failed to search locations: {str(e)}")
    
    loop = asyncio.get_running_loop()
    response_text = await loop.run_in_executor(None, _search)

    # Parse AI response
    try:
        clean_response = _strip_json_fences(response_text)
        matches = json.loads(clean_response)
        
        # Build result with full location data
        result = []
        for match in matches:
            reel_id = match.get('reel_id', '')
            location_name = match.get('location_name', '')
            relevance = match.get('relevance_reason', '')
            
            # Find the reel and location
            for reel in reels_data:
                if reel.get('id') == reel_id:
                    for loc in reel.get('locations', []):
                        if loc.get('name', '').lower() == location_name.lower():
                            result.append({
                                'name': loc.get('name', ''),
                                'latitude': loc.get('latitude'),
                                'longitude': loc.get('longitude'),
                                'display_name': loc.get('display_name', ''),
                                'geocoded': loc.get(
                                    'geocoded',
                                    loc.get('latitude') is not None
                                    and loc.get('longitude') is not None,
                                ),
                                'source_url': reel.get('url', ''),
                                'source_title': reel.get('title', ''),
                                'reel_id': reel_id,
                                'relevance_reason': relevance,
                            })
                            break
                    break
        
        return result
    except Exception as e:
        logger.warning("failed to parse AI search response: %s | raw=%r", e, response_text[:200])
        return []
