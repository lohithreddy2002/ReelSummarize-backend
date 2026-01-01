"""
Summarization service using Google Gemini API (google-genai package)
"""
import asyncio
import re
import time
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from google import genai
from google.genai import types

from config import (
    GEMINI_API_KEY, 
    GEMINI_MODEL,
    SYSTEM_INSTRUCTION,
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
            
            print(f"⏳ File state: {state}")
            
            if state == "ACTIVE":
                print(f"✅ File is now ACTIVE and ready for processing")
                return True
            elif state == "FAILED":
                raise SummarizationError(f"File processing failed on Google's servers")
            
            # Check timeout
            elapsed = time.time() - start_time
            if elapsed >= max_wait_seconds:
                raise SummarizationError(f"Timeout waiting for file to become active (waited {max_wait_seconds}s)")
            
            print(f"⏳ Waiting for file to be processed... ({int(elapsed)}s elapsed)")
            time.sleep(poll_interval)
    
    def _delete_file(self, file_name: str) -> None:
        """Delete an uploaded file from Google's File API"""
        try:
            self.client.files.delete(name=file_name)
            print(f"Uploaded file deleted: {file_name}")
        except Exception as e:
            print(f"Warning: Failed to delete uploaded file {file_name}: {e}")
    
    def _create_summary_prompt(self, context: Dict[str, Any]) -> str:
        """Create a prompt for summarization based on available context"""
        
        prompt_parts = []
        
        if context.get('title'):
            prompt_parts.append(f"Title: {context['title']}")
        
        if context.get('description'):
            prompt_parts.append(f"Description: {context['description']}")
        
        if context.get('uploader'):
            prompt_parts.append(f"Creator: {context['uploader']}")
        
        if context.get('duration'):
            duration = context['duration']
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            prompt_parts.append(f"Duration: {minutes}m {seconds}s")
        
        prompt_parts.append(METADATA_SUMMARY_PROMPT)
        
        return "\n".join(prompt_parts)
    
    def _get_video_summary_prompt(self) -> str:
        """Get the video summary prompt from config"""
        return VIDEO_SUMMARY_PROMPT
    
    def _get_system_instruction(self) -> str:
        """Get the system instruction from config"""
        return SYSTEM_INSTRUCTION
    
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
                        types.Part.from_text(text=self._get_system_instruction()),
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
        
        loop = asyncio.get_event_loop()
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
                print(f"📤 Uploading video to Gemini: {video_path}")
                try:
                    file_uri, file_name = self._upload_file(str(video_file), mime_type)
                    print(f"✅ File uploaded successfully: {file_uri}")
                except Exception as upload_error:
                    print(f"❌ File upload failed: {upload_error}")
                    raise SummarizationError(f"Failed to upload video: {str(upload_error)}")
                
                # Wait for file to be processed and become ACTIVE
                print(f"⏳ Waiting for file to be processed...")
                try:
                    self._wait_for_file_active(file_name)
                except SummarizationError:
                    raise
                except Exception as wait_error:
                    print(f"❌ Error waiting for file: {wait_error}")
                    raise SummarizationError(f"Failed waiting for file processing: {str(wait_error)}")
                
                # Build the prompt
                prompt = self._get_video_summary_prompt()
                
                # Add metadata context if available
                if metadata:
                    context_parts = []
                    if metadata.get('title'):
                        context_parts.append(f"Title: {metadata['title']}")
                    if metadata.get('uploader'):
                        context_parts.append(f"Creator: {metadata['uploader']}")
                    if context_parts:
                        prompt += f"\n\nAdditional context:\n" + "\n".join(context_parts)
                
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
                
                # Generate content - this is where the API call happens
                print(f"🤖 Calling Gemini API for summarization...")
                try:
                    response = self.client.models.generate_content(
                        model=self.model,
                        contents=contents,
                        config=config,
                    )
                    print(f"✅ Gemini API call successful")
                    return response.text
                except Exception as api_error:
                    print(f"❌ Gemini API call failed: {api_error}")
                    raise SummarizationError(f"Gemini API error: {str(api_error)}")
                
            except SummarizationError:
                raise
            except Exception as e:
                print(f"❌ Unexpected error during video analysis: {e}")
                raise SummarizationError(f"Failed to analyze video: {str(e)}")
            finally:
                # ALWAYS clean up the uploaded file, regardless of success or failure
                if file_name:
                    print(f"🧹 Cleaning up uploaded file: {file_name}")
                    self._delete_file(file_name)
        
        loop = asyncio.get_event_loop()
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
                return {
                    'summary': summary,
                    'method': 'video_analysis',
                    'success': True,
                }
            except SummarizationError as e:
                video_error = str(e)
                print(f"⚠️ Video analysis failed, falling back to metadata: {e}")
            except Exception as e:
                video_error = str(e)
                print(f"⚠️ Unexpected error in video analysis, falling back to metadata: {e}")
        
        # Fall back to metadata-based summarization
        if metadata and (metadata.get('title') or metadata.get('description')):
            try:
                summary = await self.summarize_from_metadata(metadata)
                return {
                    'summary': summary,
                    'method': 'metadata_analysis',
                    'success': True,
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
                    'latitude': loc.get('latitude', 0),
                    'longitude': loc.get('longitude', 0),
                    'display_name': loc.get('display_name', '')
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
        reels_context=reels_context
    )

    def _search():
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            
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
    
    loop = asyncio.get_event_loop()
    response_text = await loop.run_in_executor(None, _search)
    
    # Parse AI response
    try:
        import json
        # Clean up the response (remove markdown code blocks if present)
        clean_response = response_text.strip()
        if clean_response.startswith('```'):
            # Remove code block markers
            clean_response = clean_response.split('\n', 1)[1]  # Remove first line
            if clean_response.endswith('```'):
                clean_response = clean_response[:-3]
            clean_response = clean_response.strip()
        
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
                                'latitude': loc.get('latitude', 0),
                                'longitude': loc.get('longitude', 0),
                                'display_name': loc.get('display_name', ''),
                                'source_url': reel.get('url', ''),
                                'source_title': reel.get('title', ''),
                                'reel_id': reel_id,
                                'relevance_reason': relevance,
                            })
                            break
                    break
        
        return result
    except Exception as e:
        print(f"Failed to parse AI response: {e}")
        print(f"Response was: {response_text}")
        return []
