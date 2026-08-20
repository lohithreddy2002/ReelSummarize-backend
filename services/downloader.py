"""
Media downloader service using yt-dlp, with instaloader tried first for
Instagram URLs (works anonymously, no cookies needed - yt-dlp is the
fallback for when Instagram rate-limits/blocks the anonymous path).
"""
import logging
import os
import re
import uuid
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
import httpx
import instaloader
import yt_dlp

from config import DOWNLOAD_DIR, MAX_VIDEO_DURATION, YTDLP_COOKIES_FILE

logger = logging.getLogger(__name__)

_IG_SHORTCODE_RE = re.compile(r'instagram\.com/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)')


class DownloadError(Exception):
    """Custom exception for download errors"""
    pass


class MediaDownloader:
    """Service for downloading media from Instagram and other platforms"""
    
    def __init__(self):
        self.download_dir = DOWNLOAD_DIR
        
    def _get_ydl_opts(self, output_path: Path) -> Dict[str, Any]:
        """Get yt-dlp options for downloading"""
        opts: Dict[str, Any] = {
            'outtmpl': str(output_path / '%(id)s.%(ext)s'),
            'format': 'best[ext=mp4]/best',
            'quiet': True,
            'no_warnings': True,
            'extractaudio': False,
            'keepvideo': True,
            'merge_output_format': 'mp4',
            'postprocessors': [],
            # Limit video duration
            'match_filter': yt_dlp.utils.match_filter_func(
                f'duration <= {MAX_VIDEO_DURATION}'
            ) if MAX_VIDEO_DURATION else None,
        }
        if YTDLP_COOKIES_FILE:
            opts['cookiefile'] = YTDLP_COOKIES_FILE
        return opts

    def _get_info_opts(self) -> Dict[str, Any]:
        """Get yt-dlp options for extracting info only"""
        opts: Dict[str, Any] = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'skip_download': True,
        }
        if YTDLP_COOKIES_FILE:
            opts['cookiefile'] = YTDLP_COOKIES_FILE
        return opts
    
    def _extract_instaloader_info(self, url: str) -> Optional[Dict[str, Any]]:
        """Try instaloader (anonymous, no cookies) for an Instagram URL. Returns None on any failure."""
        match = _IG_SHORTCODE_RE.search(url)
        if not match:
            return None
        try:
            context = instaloader.InstaloaderContext(quiet=True)
            post = instaloader.Post.from_shortcode(context, match.group(1))
            return {
                'id': post.shortcode,
                'title': f"Video by {post.owner_username}",
                'description': post.caption or '',
                'duration': post.video_duration if post.is_video else 0,
                'uploader': post.owner_username,
                'thumbnail': post.url,
                'view_count': post.video_view_count if post.is_video else 0,
                'like_count': post.likes,
                'platform': 'Instagram',
                'video_url': post.video_url if post.is_video else post.url,
            }
        except Exception as e:
            logger.info("instaloader: falling back to yt-dlp for '%s' (%s)", url, e)
            return None

    async def get_media_info(self, url: str) -> Dict[str, Any]:
        """
        Extract media information without downloading

        Args:
            url: The media URL

        Returns:
            Dictionary with media information
        """
        loop = asyncio.get_event_loop()
        instaloader_info = await loop.run_in_executor(None, self._extract_instaloader_info, url)
        if instaloader_info is not None:
            return instaloader_info

        def _extract_info():
            with yt_dlp.YoutubeDL(self._get_info_opts()) as ydl:
                try:
                    info = ydl.extract_info(url, download=False)
                    
                    # Extract direct video URL if available
                    video_url = None
                    if 'url' in info:
                        # For single video formats
                        video_url = info.get('url')
                    elif 'formats' in info and info['formats']:
                        # Find the best video format
                        video_formats = [f for f in info['formats'] if f.get('vcodec') != 'none']
                        if video_formats:
                            # Prefer mp4 format, then best quality
                            mp4_format = next((f for f in video_formats if f.get('ext') == 'mp4'), None)
                            if mp4_format:
                                video_url = mp4_format.get('url')
                            else:
                                # Get the format with highest quality
                                best_format = max(video_formats, key=lambda f: f.get('height', 0) or f.get('quality', 0))
                                video_url = best_format.get('url')
                    
                    return {
                        'id': info.get('id', ''),
                        'title': info.get('title', ''),
                        'description': info.get('description', ''),
                        'duration': info.get('duration', 0),
                        'uploader': info.get('uploader', ''),
                        'thumbnail': info.get('thumbnail', ''),
                        'view_count': info.get('view_count', 0),
                        'like_count': info.get('like_count', 0),
                        'platform': info.get('extractor_key', 'Unknown'),
                        'video_url': video_url,
                    }
                except Exception as e:
                    raise DownloadError(f"Failed to extract info: {str(e)}")

        # Run in thread pool to not block async event loop
        return await loop.run_in_executor(None, _extract_info)
    
    async def _download_direct_url(
        self, video_url: str, output_path: Path, info: Dict[str, Any], request_id: str
    ) -> Dict[str, Any]:
        """Download an already-resolved CDN video_url (from instaloader/yt-dlp info) directly."""
        dest = output_path / f"{info.get('id') or request_id}.mp4"
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            async with client.stream('GET', video_url) as resp:
                resp.raise_for_status()
                with open(dest, 'wb') as f:
                    async for chunk in resp.aiter_bytes(chunk_size=1 << 16):
                        f.write(chunk)
        return {
            **info,
            'file_path': str(dest),
            'request_id': request_id,
        }

    async def download_media(self, url: str) -> Dict[str, Any]:
        """
        Download media from URL. Tries instaloader/yt-dlp info + a direct CDN
        download first (fast, no extra extraction pass); falls back to a full
        yt-dlp download if that fails for any reason.

        Args:
            url: The media URL

        Returns:
            Dictionary with download info including file path
        """
        # Create unique download folder for this request
        request_id = str(uuid.uuid4())[:8]
        output_path = self.download_dir / request_id
        output_path.mkdir(parents=True, exist_ok=True)

        try:
            info = await self.get_media_info(url)
            if info.get('video_url'):
                return await self._download_direct_url(info['video_url'], output_path, info, request_id)
        except Exception as e:
            logger.info("direct video_url download failed, falling back to yt-dlp download: %s", e)

        def _download():
            opts = self._get_ydl_opts(output_path)
            with yt_dlp.YoutubeDL(opts) as ydl:
                try:
                    info = ydl.extract_info(url, download=True)
                    
                    # Find the downloaded file
                    downloaded_file = None
                    for file in output_path.iterdir():
                        if file.is_file() and file.suffix in ['.mp4', '.webm', '.mkv', '.mov']:
                            downloaded_file = file
                            break
                    
                    if not downloaded_file:
                        # Check for any file
                        files = list(output_path.iterdir())
                        if files:
                            downloaded_file = files[0]
                    
                    return {
                        'id': info.get('id', request_id),
                        'title': info.get('title', ''),
                        'description': info.get('description', ''),
                        'duration': info.get('duration', 0),
                        'uploader': info.get('uploader', ''),
                        'thumbnail': info.get('thumbnail', ''),
                        'view_count': info.get('view_count', 0),
                        'like_count': info.get('like_count', 0),
                        'file_path': str(downloaded_file) if downloaded_file else None,
                        'request_id': request_id,
                        'platform': info.get('extractor_key', 'Unknown'),
                    }
                except yt_dlp.utils.DownloadError as e:
                    raise DownloadError(f"Download failed: {str(e)}")
                except Exception as e:
                    raise DownloadError(f"Unexpected error: {str(e)}")
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _download)
    
    def cleanup(self, request_id: str) -> None:
        """
        Clean up downloaded files for a request
        
        Args:
            request_id: The request ID to clean up
        """
        import shutil
        folder_path = self.download_dir / request_id
        if folder_path.exists():
            shutil.rmtree(folder_path)
    
    def cleanup_all(self) -> None:
        """Clean up all downloaded files"""
        import shutil
        if self.download_dir.exists():
            for item in self.download_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()


# Singleton instance
downloader = MediaDownloader()

