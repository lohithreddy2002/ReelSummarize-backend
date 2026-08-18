"""
Media downloader service using yt-dlp
"""
import os
import uuid
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
import yt_dlp

from config import DOWNLOAD_DIR, MAX_VIDEO_DURATION, YTDLP_COOKIES_FILE


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
    
    async def get_media_info(self, url: str) -> Dict[str, Any]:
        """
        Extract media information without downloading
        
        Args:
            url: The media URL
            
        Returns:
            Dictionary with media information
        """
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
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _extract_info)
    
    async def download_media(self, url: str) -> Dict[str, Any]:
        """
        Download media from URL
        
        Args:
            url: The media URL
            
        Returns:
            Dictionary with download info including file path
        """
        # Create unique download folder for this request
        request_id = str(uuid.uuid4())[:8]
        output_path = self.download_dir / request_id
        output_path.mkdir(parents=True, exist_ok=True)
        
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

