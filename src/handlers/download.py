"""
Download handler for Terabox videos
"""
import os
import re
import logging
import aiohttp
import asyncio
import subprocess
import json
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse
import config

logger = logging.getLogger(__name__)


def is_valid_stream_url(url: str) -> bool:
    """
    Check if a URL looks like an actual media stream and not a Terabox page or error page
    """
    if not url or not isinstance(url, str):
        return False
    
    # Reject URLs that are Terabox share links (these are not streams)
    if 'terabox.com' in url.lower() or '1024terabox.com' in url.lower():
        logger.debug(f"URL is a Terabox share link, not a stream: {url[:80]}")
        return False
    
    # Accept URLs that are CDN/streaming domains (common video hosting)
    streaming_domains = [
        'teraboxapi',
        'iteraplay',
        'cloudflare',
        'cdn',
        'stream',
        'video',
        'media',
        '.mp4',
        '.m3u8',
        '.flv',
        '.mkv',
        '.avi',
    ]
    
    url_lower = url.lower()
    for domain in streaming_domains:
        if domain in url_lower:
            return True
    
    logger.debug(f"URL doesn't match known streaming domains: {url[:80]}")
    return False


async def extract_terabox_url(url: str) -> Optional[str]:
    """
    Extract valid Terabox URL from user input
    Supports:
    - Direct Terabox links
    - Share links
    - Folder links
    - Auto-corrects common domain typos (teraboxlink.com -> terabox.com)
    """
    url = url.strip()
    
    # Quick check that it looks like a URL
    if not url.lower().startswith(('http://', 'https://')):
        return None

    # Correct common domain typos/redirects
    # Many shortlinks or old links use teraboxlink.com which should be terabox.com
    url = re.sub(r'teraboxlink\.com', 'terabox.com', url, flags=re.IGNORECASE)
    
    # Ensure it's a terabox domain
    if 'terabox' in url.lower():
        return url

    return None


async def fetch_stream_url(terabox_url: str) -> Optional[Tuple[str, str]]:
    """
    Fetch streaming URL from iTeraPlay API and fallback APIs
    Returns: (stream_url, filename) or (None, None) if failed
    """
    
    # List of APIs to try
    api_urls_to_try = [
        config.TERABOX_API.format(url=terabox_url),  # Primary
    ]
    if hasattr(config, 'TERABOX_API_FALLBACKS'):
        api_urls_to_try.extend([
            api_url.format(url=terabox_url) 
            for api_url in config.TERABOX_API_FALLBACKS
        ])
    
    last_error = None
    
    for api_attempt, api_url in enumerate(api_urls_to_try, 1):
        logger.info(f"Attempting API {api_attempt}/{len(api_urls_to_try)}: {api_url[:80]}...")
        
        try:
            api_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
                'Referer': 'https://terabox.com/',
                'Accept': '*/*',
            }

            async with aiohttp.ClientSession(headers=api_headers) as session:
                async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=config.TIMEOUT)) as response:
                    logger.info(f"API {api_attempt} Response Status: {response.status}")

                    if response.status == 404:
                        logger.warning(f"API {api_attempt} returned 404")
                        last_error = "API returned 404"
                        continue
                    
                    if response.status != 200:
                        logger.warning(f"API {api_attempt} returned status {response.status}")
                        last_error = f"API returned {response.status}"
                        continue

                    # Try JSON first
                    text = await response.text()
                    
                    try:
                        data = json.loads(text)
                        if isinstance(data, dict):
                            stream_url = None
                            filename = None

                            for key in ("url", "stream_url", "play_url", "video_url"):
                                if key in data and data[key]:
                                    stream_url = data[key]
                                    break

                            if not stream_url and isinstance(data.get('data'), dict):
                                for key in ("url", "stream_url", "play_url", "video_url"):
                                    if key in data['data'] and data['data'][key]:
                                        stream_url = data['data'][key]
                                        break

                            for key in ("filename", "title", "name"):
                                if key in data and data[key]:
                                    filename = data[key]
                                    break
                            if not filename and isinstance(data.get('data'), dict):
                                for key in ("filename", "title", "name"):
                                    if key in data['data'] and data['data'][key]:
                                        filename = data['data'][key]
                                        break

                            if stream_url and is_valid_stream_url(stream_url):
                                filename = filename or os.path.basename(urlparse(stream_url).path) or 'terabox_video.mp4'
                                filename = re.sub(r'[<>:"\\\\/|?*]', '', filename)
                                if not filename.endswith(('.mp4', '.mkv', '.avi', '.mov')):
                                    filename += '.mp4'
                                logger.info(f"API {api_attempt} - Stream URL from JSON: {stream_url[:80]}")
                                return stream_url, filename
                            elif stream_url:
                                logger.warning(f"API {api_attempt} - Returned URL looks like Terabox link, not a stream URL: {stream_url[:80]}")
                                last_error = "API returned invalid stream URL (looks like Terabox link)"
                                continue
                    except json.JSONDecodeError:
                        pass
                    
                    logger.debug(f"API {api_attempt} response text length: {len(text)} bytes")
                    
                    # Try regex extraction from text
                    for resolution in ["360p", "480p", "720p", "1080p"]:
                        pattern = rf'"{resolution}"\s*:\s*"([^"]+)"'
                        match = re.search(pattern, text)
                        if match:
                            stream_url = match.group(1).replace('\\/', '/')
                            if is_valid_stream_url(stream_url):
                                filename = f'terabox_video_{resolution}.mp4'
                                logger.info(f"API {api_attempt} - Found {resolution} URL: {stream_url[:80]}")
                                return stream_url, filename
                            else:
                                logger.debug(f"API {api_attempt} - {resolution} URL failed validation: {stream_url[:80]}")
                    
                    # Search for m3u8
                    m3u8_patterns = [
                        r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)',
                        r'["\'](https?://[^"\']*?\.m3u8[^"\']*)["\']',
                    ]
                    for pattern in m3u8_patterns:
                        m3u8_match = re.search(pattern, text)
                        if m3u8_match:
                            stream_url = m3u8_match.group(1).replace('\\/', '/').replace('\\:', ':')
                            if is_valid_stream_url(stream_url):
                                logger.info(f"API {api_attempt} - Found m3u8 URL: {stream_url[:80]}")
                                return stream_url, 'terabox_video.mp4'
                    
                    # Search for mp4
                    mp4_patterns = [
                        r'(https?://[^\s"\'<>]*\.mp4[^\s"\'<>]*)',
                        r'["\'](https?://[^"\']*?\.mp4[^"\']*)["\']',
                    ]
                    for pattern in mp4_patterns:
                        mp4_match = re.search(pattern, text)
                        if mp4_match:
                            stream_url = mp4_match.group(1).replace('\\/', '/').replace('\\:', ':')
                            if is_valid_stream_url(stream_url):
                                filename = os.path.basename(urlparse(stream_url).path) or 'terabox_video.mp4'
                                logger.info(f"API {api_attempt} - Found mp4 URL: {stream_url[:80]}")
                                return stream_url, filename

                    logger.warning(f"API {api_attempt} - Could not extract stream")
                    last_error = "Could not extract from response"
                
        except asyncio.TimeoutError:
            logger.warning(f"API {api_attempt} timeout")
            last_error = "API timeout"
        except Exception as e:
            logger.warning(f"API {api_attempt} error: {e}")
            last_error = f"API error: {str(e)[:50]}"
    
    # Try direct Terabox page as last resort
    logger.info("Trying Terabox page directly as fallback")
    try:
        page_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
            'Referer': 'https://terabox.com/',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        async with aiohttp.ClientSession(headers=page_headers) as session:
            async with session.get(terabox_url, timeout=aiohttp.ClientTimeout(total=config.TIMEOUT), ssl=False) as page_resp:
                if page_resp.status == 200:
                    page_text = await page_resp.text()
                    logger.debug(f"Terabox page fetched, length: {len(page_text)} bytes")
                    
                    # Search for playUrl or other stream URLs in page
                    playurl_pattern = r'"playUrl"\s*:\s*"([^"]+)"'
                    match = re.search(playurl_pattern, page_text)
                    if match:
                        stream_url = match.group(1).replace('\\/', '/')
                        if is_valid_stream_url(stream_url):
                            logger.info(f"Fallback - Found playUrl: {stream_url[:80]}")
                            return stream_url, 'terabox_video.mp4'
                    
                    # Try resolutions
                    for resolution in ["360p", "480p", "720p", "1080p"]:
                        pattern = rf'"{resolution}"\s*:\s*"([^"]+)"'
                        match = re.search(pattern, page_text)
                        if match:
                            stream_url = match.group(1).replace('\\/', '/')
                            if is_valid_stream_url(stream_url):
                                logger.info(f"Fallback - Found {resolution} URL: {stream_url[:80]}")
                                return stream_url, f'terabox_video_{resolution}.mp4'
                    
                    # Try to find any m3u8 URLs
                    m3u8_patterns = [
                        r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)',
                        r'["\'](https?://[^"\']*?\.m3u8[^"\']*)["\']',
                    ]
                    for pattern in m3u8_patterns:
                        m3u8_match = re.search(pattern, page_text)
                        if m3u8_match:
                            stream_url = m3u8_match.group(1).replace('\\/', '/').replace('\\:', ':')
                            if is_valid_stream_url(stream_url):
                                logger.info(f"Fallback - Found m3u8 URL: {stream_url[:80]}")
                                return stream_url, 'terabox_video.mp4'
                    
                    logger.warning("Could not find any valid stream URLs in Terabox page")
    except Exception as e:
        logger.debug(f"Fallback page fetch failed: {e}")

    logger.error(f"All extraction methods failed. Last: {last_error}")
    return None, None


async def download_video(stream_url: str, filename: str) -> Optional[str]:
    """
    Download video from stream URL
    Supports both direct MP4 URLs and M3U8 HLS streams
    Returns: file path if successful, None otherwise
    """
    try:
        # Ensure download directory exists
        Path(config.DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)
        file_path = os.path.join(config.DOWNLOAD_DIR, filename)
        
        logger.info(f"Starting download: {filename} from {stream_url[:100]}")
        
        # Check if it's an M3U8 stream (HLS format)
        is_m3u8 = '.m3u8' in stream_url.lower() or 'playlist' in stream_url.lower()
        
        if is_m3u8:
            # Use FFmpeg for M3U8 streams
            logger.info("Detected M3U8 stream - using FFmpeg")
            return await _download_m3u8_with_ffmpeg(stream_url, file_path, filename)
        else:
            # Use direct HTTP download for MP4/direct streams
            logger.info("Detected direct stream - using HTTP download")
            return await _download_direct_http(stream_url, file_path, filename)
                    
    except asyncio.TimeoutError:
        logger.error("Download timed out")
        if os.path.exists(file_path):
            os.remove(file_path)
        return None
    except Exception as e:
        logger.error(f"Error downloading video: {e}", exc_info=True)
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)
        return None


def check_ffmpeg_available() -> bool:
    """Check if FFmpeg is available on the system"""
    try:
        result = subprocess.run(['which', 'ffmpeg'], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


async def _download_direct_http(stream_url: str, file_path: str, filename: str) -> Optional[str]:
    """
    Download video via direct HTTP request
    """
    try:
        # Validate stream URL format first
        if not stream_url or not isinstance(stream_url, str):
            logger.error(f"Invalid stream URL: {stream_url}")
            return None
        
        if not stream_url.startswith(('http://', 'https://')):
            logger.error(f"Stream URL is not HTTP(S): {stream_url[:100]}")
            return None
        
        # Headers to mimic a browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://terabox.com/',
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }
        
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=600), ssl=False, allow_redirects=True) as response:
                logger.info(f"Download Response Status: {response.status}")
                logger.info(f"Content-Length: {response.content_length}")
                logger.info(f"Content-Type: {response.content_type}")
                
                if response.status != 200:
                    logger.error(f"Stream returned status code {response.status}")
                    return None
                
                # Check for HTML content - indicates error/login page
                content_type = response.content_type or ""
                if "text/html" in content_type.lower():
                    logger.error(f"Received HTML content instead of video (Content-Type: {content_type})")
                    return None
                
                # Check file size before downloading
                content_length = response.content_length
                if content_length and content_length > config.MAX_FILE_SIZE:
                    logger.error(f"File too large: {content_length} bytes (max: {config.MAX_FILE_SIZE})")
                    return None
                
                # Download file with progress tracking
                downloaded_size = 0
                with open(file_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(65536):  # 64KB chunks
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            if downloaded_size % (1024 * 1024) == 0:  # Log every 1MB
                                logger.debug(f"Downloaded {downloaded_size / (1024*1024):.1f}MB")
                
                file_size = os.path.getsize(file_path)
                logger.info(f"Final file size: {file_size} bytes ({file_size/(1024*1024):.2f}MB)")
                
                # Validate that we got a real video file
                if file_size < 5000:  # Less than 5KB is almost certainly not a real video
                    logger.error(f"Downloaded file is suspiciously small: {file_size} bytes - likely dummy/error response")
                    os.remove(file_path)
                    return None
                
                # Read first few bytes to check if it's HTML or error page (corruption check)
                with open(file_path, 'rb') as f:
                    header = f.read(500)
                    
                    # Check for HTML signatures
                    if any(sig in header for sig in [b'<!DOCTYPE', b'<html', b'<HTML', b'<?xml', b'<svg', b'<script', b'<meta', b'error', b'Error', b'ERROR']):
                        logger.error(f"Downloaded file appears to be HTML/error page. First 200 bytes: {header[:200]}")
                        os.remove(file_path)
                        return None
                    
                    # Check for valid video/media file signatures
                    valid_signatures = [
                        b'\x00\x00\x00',  # MP4 ftyp
                        b'RIFF',  # AVI
                        b'\x1a\x45\xdf\xa3',  # WebM
                        b'\xff\xfb',  # MP3
                        b'\x49\x44\x33',  # ID3 (MP3 tag)
                        b'#EXT',  # M3U8/HLS playlist (starts with #EXTM3U)
                        b'#EXTM3U',  # M3U8 full header
                    ]
                    
                    is_valid = any(sig in header[:50] for sig in valid_signatures)
                    
                    if not is_valid:
                        logger.warning(f"File signature not recognized as video. First bytes: {header[:50].hex()}")
                
                logger.info(f"Download complete: {filename} ({file_size} bytes / {file_size/(1024*1024):.2f}MB)")
                return file_path
                    
    except Exception as e:
        logger.error(f"Error downloading video via HTTP: {e}", exc_info=True)
        if os.path.exists(file_path):
            os.remove(file_path)
        return None


async def _download_m3u8_with_ffmpeg(stream_url: str, file_path: str, filename: str) -> Optional[str]:
    """
    Download M3U8 HLS stream using FFmpeg
    """
    try:
        # Check if FFmpeg is available
        if not check_ffmpeg_available():
            logger.error("FFmpeg is not installed on the system")
            return None
        
        # FFmpeg command to download M3U8 stream
        # -allowed_extensions ALL: Allow any extension in playlist
        # -c copy: Copy without re-encoding (fast)
        # -bsf:a aac_adtstoasc: Convert AAC to MP4 compatible format
        cmd = [
            'ffmpeg',
            '-protocol_whitelist', 'file,http,https,tcp,tls,crypto',
            '-allowed_extensions', 'ALL',
            '-i', stream_url,
            '-c', 'copy',
            '-bsf:a', 'aac_adtstoasc',
            '-y',  # Overwrite output file
            '-loglevel', 'info',
            file_path
        ]
        logger.info(f"Running FFmpeg: {' '.join(cmd)}")
        
        # Run FFmpeg as subprocess
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=600)
        
        if process.returncode != 0:
            logger.error(f"FFmpeg failed with return code {process.returncode}")
            logger.error(f"Stderr: {stderr.decode('utf-8', errors='ignore')}")
            if os.path.exists(file_path):
                os.remove(file_path)
            return None
        
        file_size = os.path.getsize(file_path)
        
        if file_size < 100000:  # Less than 100KB is likely corrupted
            logger.error(f"Downloaded file is suspiciously small: {file_size} bytes - likely corrupted")
            os.remove(file_path)
            return None
        
        logger.info(f"Download complete: {filename} ({file_size} bytes / {file_size/(1024*1024):.1f}MB)")
        return file_path
        
    except asyncio.TimeoutError:
        logger.error("FFmpeg download timed out")
        if os.path.exists(file_path):
            os.remove(file_path)
        return None
    except Exception as e:
        logger.error(f"Error downloading M3U8 stream: {e}", exc_info=True)
        if os.path.exists(file_path):
            os.remove(file_path)
        return None


async def process_terabox_link(url: str) -> Optional[Tuple[str, str]]:
    """
    Complete pipeline: validate -> fetch stream -> download
    Returns: (file_path, filename) or (None, None)
    """
    # Validate URL
    terabox_url = await extract_terabox_url(url)
    if not terabox_url:
        logger.warning(f"Invalid Terabox URL: {url}")
        return None, None
    
    # Fetch stream URL
    stream_url, filename = await fetch_stream_url(terabox_url)
    if not stream_url:
        logger.warning("Failed to fetch stream URL")
        return None, None
    
    # Download video
    downloads_dir = Path("downloads")
    downloads_dir.mkdir(exist_ok=True)
    
    # Clean filename
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    if not filename.endswith(('.mp4', '.mkv', '.avi', '.mov', '.webm')):
        filename += '.mp4'
    
    file_path = downloads_dir / filename
    
    file_path = await _download_direct_http(str(stream_url), str(file_path), filename)
    if not file_path:
        logger.warning("Failed to download video")
        return None, None
    
    return file_path, filename
