"""
Download handler for Terabox videos
"""
import os
import re
import logging
import aiohttp
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse
import config

logger = logging.getLogger(__name__)


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
    Fetch streaming URL from iTeraPlay API
    Returns: (stream_url, filename) or (None, None) if failed
    """
    api_url = config.TERABOX_API.format(url=terabox_url)
    logger.info(f"Fetching stream URL for: {terabox_url} -> {api_url}")

    try:
        # Use browser-like headers for API call and retry once if anti-bot page detected
        api_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
            'Referer': 'https://terabox.com/',
            'Accept': '*/*',
        }

        async with aiohttp.ClientSession(headers=api_headers) as session:
            # Try a couple of times if the API returns an anti-bot page
            anti_bot_detected = False
            for attempt in range(2):
                async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=config.TIMEOUT)) as response:
                    logger.info(f"API Response Status: {response.status}")

                    # If Cloudflare/anti-bot HTML returned, retry once
                    try:
                        peek = await response.text()
                    except Exception:
                        peek = ''
                    if response.status in (403, 520) or 'Bot Verification' in peek or 'recaptcha' in peek.lower():
                        logger.warning(f"API appears to be protected by anti-bot (status {response.status}). Attempt {attempt+1}.")
                        anti_bot_detected = True
                        if attempt == 0:
                            await asyncio.sleep(1)
                            continue
                        else:
                            # proceed to fallback extraction below
                            text = peek
                            logger.debug("Proceeding to fallback extraction after anti-bot detection")
                    else:
                        # normal flow: try JSON / text parsing below
                        # reset stream to beginning by using peek as text
                        text = peek
                
                if response.status == 404:
                    logger.error(f"API returned 404 - Link may be invalid or expired")
                    return None, None
                    
                if response.status != 200:
                    logger.error(f"API returned status code {response.status}")
                    # Try to fallback to response URL if it redirected
                    if response.url and str(response.url) != api_url:
                        candidate = str(response.url)
                        logger.info(f"Using redirect URL as candidate stream: {candidate}")
                        return candidate, os.path.basename(urlparse(candidate).path) or 'terabox_video.mp4'
                    return None, None

                # Try JSON first
                try:
                    data = await response.json()
                except Exception as e:
                    logger.debug(f"Response is not JSON: {e}")
                    data = None

                # If JSON present, try a few common shapes
                if isinstance(data, dict):
                    # common keys in different APIs
                    stream_url = None
                    filename = None

                    # Direct url fields
                    for key in ("url", "stream_url", "play_url", "video_url"):
                        if key in data and data[key]:
                            stream_url = data[key]
                            break

                    # Some APIs wrap values under 'data' or 'result'
                    if not stream_url and isinstance(data.get('data'), dict):
                        for key in ("url", "stream_url", "play_url", "video_url"):
                            if key in data['data'] and data['data'][key]:
                                stream_url = data['data'][key]
                                break

                    # filename/title
                    for key in ("filename", "title", "name"):
                        if key in data and data[key]:
                            filename = data[key]
                            break
                    if not filename and isinstance(data.get('data'), dict):
                        for key in ("filename", "title", "name"):
                            if key in data['data'] and data['data'][key]:
                                filename = data['data'][key]
                                break

                    if stream_url:
                        filename = filename or os.path.basename(urlparse(stream_url).path) or 'terabox_video.mp4'
                        filename = re.sub(r'[<>:\"/\\|?*]', '', filename)
                        if not filename.endswith(('.mp4', '.mkv', '.avi', '.mov')):
                            filename += '.mp4'
                        logger.info(f"Stream URL fetched from JSON: {stream_url[:80]}")
                        return stream_url, filename

                # If not JSON or couldn't extract, try to read text and search for video URLs
                text = await response.text()
                logger.debug(f"Response text length: {len(text)} bytes")
                
                # First priority: Look for videoQualities (standard TeraBox player format)
                # Try different resolution options in order of preference
                for resolution in ["360p", "480p", "720p", "1080p", "playUrl"]:
                    pattern = rf'"{resolution}"\s*:\s*"([^"]+)"'
                    match = re.search(pattern, text)
                    if match:
                        stream_url = match.group(1)
                        # Unescape forward slashes
                        stream_url = stream_url.replace('\\/', '/')
                        filename = f'terabox_video_{resolution}.mp4'
                        logger.info(f"Found {resolution} stream URL: {stream_url[:80]}")
                        return stream_url, filename
                
                # Search for m3u8 (HLS stream) URLs - handle escaped JSON strings too
                m3u8_patterns = [
                    r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)',  # plain URL
                        r'["\'](https?://[^"\']*?\.m3u8[^"\']*)["\']',  # m3u8 inside quotes (must be a URL)
                ]
                for pattern in m3u8_patterns:
                    m3u8_match = re.search(pattern, text)
                    if m3u8_match:
                        stream_url = m3u8_match.group(1)
                        # Unescape if necessary
                        stream_url = stream_url.replace('\\/', '/').replace('\\:', ':')
                        filename = 'terabox_video.mp4'
                        logger.info(f"Found m3u8 stream URL: {stream_url[:80]}")
                        return stream_url, filename
                
                # Search for mp4 URLs
                mp4_patterns = [
                    r'(https?://[^\s"\'<>]*\.mp4[^\s"\'<>]*)',  # plain URL
                        r'["\'](https?://[^"\']*?\.mp4[^"\']*)["\']',  # mp4 inside quotes (must be a URL)
                ]
                for pattern in mp4_patterns:
                    mp4_match = re.search(pattern, text)
                    if mp4_match:
                        stream_url = mp4_match.group(1)
                        stream_url = stream_url.replace('\\/', '/').replace('\\:', ':')
                        filename = os.path.basename(urlparse(stream_url).path) or 'terabox_video.mp4'
                        logger.info(f"Found mp4 stream URL: {stream_url[:80]}")
                        return stream_url, filename

                # If we couldn't extract from the iTeraPlay API response, try fetching the original Terabox page
                logger.info("Attempting fallback: fetch Terabox page directly to extract stream URL")
                try:
                    # Browser-like headers to avoid simple bot blocks
                    page_headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Referer': 'https://terabox.com/'
                    }
                    async with session.get(terabox_url, headers=page_headers, timeout=aiohttp.ClientTimeout(total=config.TIMEOUT), ssl=False, allow_redirects=True) as page_resp:
                        logger.info(f"Terabox page response status: {page_resp.status}")
                        if page_resp.status == 200:
                            page_text = await page_resp.text()

                            # Try the same extraction logic on the page
                            for resolution in ["360p", "480p", "720p", "1080p", "playUrl"]:
                                pattern = rf'"{resolution}"\s*:\s*"([^\"]+)"'
                                match = re.search(pattern, page_text)
                                if match:
                                    stream_url = match.group(1).replace('\\/', '/')
                                    filename = f'terabox_video_{resolution}.mp4'
                                    logger.info(f"Found {resolution} stream URL on page: {stream_url[:80]}")
                                    return stream_url, filename

                            # m3u8 on page
                            for pattern in m3u8_patterns:
                                m3u8_match = re.search(pattern, page_text)
                                if m3u8_match:
                                    stream_url = m3u8_match.group(1).replace('\\/', '/').replace('\\:', ':')
                                    filename = 'terabox_video.mp4'
                                    logger.info(f"Found m3u8 stream URL on page: {stream_url[:80]}")
                                    return stream_url, filename

                            # mp4 on page
                            for pattern in mp4_patterns:
                                mp4_match = re.search(pattern, page_text)
                                if mp4_match:
                                    stream_url = mp4_match.group(1).replace('\\/', '/').replace('\\:', ':')
                                    filename = os.path.basename(urlparse(stream_url).path) or 'terabox_video.mp4'
                                    logger.info(f"Found mp4 stream URL on page: {stream_url[:80]}")
                                    return stream_url, filename
                        else:
                            logger.warning(f"Terabox page returned status {page_resp.status}")
                except Exception as e:
                    logger.debug(f"Fallback page fetch failed: {e}")

                # If anti-bot detected, raise a specific error so caller can inform the user
                if anti_bot_detected:
                    logger.error("Anti-bot protection detected when fetching stream URL")
                    raise RuntimeError("anti-bot-detected")

                logger.warning(f"Unable to extract stream URL from API response (response length: {len(text)})")
                return None, None

    except asyncio.TimeoutError:
        logger.error("API request timed out")
        return None, None
    except Exception as e:
        logger.error(f"Error fetching stream URL: {e}", exc_info=True)
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
        # Headers to mimic a browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://iteraplay.com/',
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
                
                # Validate that we got a real video file
                if file_size < 1000:  # Less than 1KB is almost certainly not a real video
                    logger.error(f"Downloaded file is suspiciously small: {file_size} bytes - likely dummy/error response")
                    os.remove(file_path)
                    return None
                
                # Read first few bytes to check if it's HTML (corruption check)
                with open(file_path, 'rb') as f:
                    header = f.read(100)
                    if header.startswith(b'<!DOCTYPE') or header.startswith(b'<html') or b'<html' in header[:200]:
                        logger.error(f"Downloaded file contains HTML - likely an error/login page")
                        os.remove(file_path)
                        return None
                
                logger.info(f"Download complete: {filename} ({file_size} bytes / {file_size/(1024*1024):.1f}MB)")
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
    Process a Terabox link using the iTeraPlay API endpoint.
    Returns: (file_path, filename) or (None, None) if failed
    """
    # Use the primary iTeraPlay API from config
    api_url = config.TERABOX_API.format(url=url)
    logger.info(f"Processing Terabox link: {url} using API: {api_url}")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=60)) as response:
                logger.info(f"API Response Status: {response.status}")
                logger.info(f"Response Content-Type: {response.content_type}")
                logger.info(f"Response Content-Length: {response.content_length}")
                
                if response.status == 200:
                    content_type = response.content_type or ""
                    
                    # If it's HTML, it's an error page
                    if "text/html" in content_type.lower():
                        logger.error("API returned HTML error page")
                        return None, None
                    
                    # Try to parse JSON response first
                    try:
                        data = await response.json()
                        logger.info(f"API returned JSON: {str(data)[:200]}")
                        
                        file_url = data.get("file_url") or data.get("url") or data.get("play_url") or data.get("stream_url")
                        filename = data.get("filename", "terabox_video.mp4")
                        
                        if not file_url:
                            logger.error("API response did not contain a valid file URL")
                            logger.debug(f"API response data: {data}")
                            return None, None
                    except Exception as e:
                        logger.warning(f"Failed to parse JSON response: {e}")
                        # If not JSON, treat as direct video stream if content looks like video
                        logger.info("Treating response as direct video stream")
                        file_url = api_url
                        filename = "terabox_video.mp4"
                    
                    # Validate file URL
                    if not isinstance(file_url, str) or not file_url.startswith(('http://', 'https://')):
                        logger.error(f"Invalid file URL received from API: {file_url}")
                        return None, None
                    
                    # Download the file
                    downloads_dir = Path("downloads")
                    downloads_dir.mkdir(exist_ok=True)
                    
                    # Clean filename
                    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
                    if not filename.endswith(('.mp4', '.mkv', '.avi', '.mov', '.webm')):
                        filename += '.mp4'
                    
                    file_path = downloads_dir / filename
                    
                    # Download the video file
                    file_path = await _download_direct_http(file_url, str(file_path), filename)
                    
                    if file_path:
                        return file_path, filename
                    else:
                        logger.error("Failed to download video from API URL")
                        return None, None
                else:
                    response_text = await response.text()
                    logger.error(f"API returned status code {response.status}")
                    logger.debug(f"Response: {response_text[:300]}")
                    return None, None
    except asyncio.TimeoutError:
        logger.error(f"API request to {api_url} timed out")
        return None, None
    except Exception as e:
        logger.exception(f"Error processing Terabox link: {e}")
        return None, None
