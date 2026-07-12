# -*- coding: utf-8 -*-
"""Yuafeng.cn music API client - supports VIP song downloads.

Register at http://api-v2.yuafeng.cn to get a free API key.
Set your key below or via YUAFENG_API_KEY environment variable.
"""

import os
import re
import requests
from typing import Optional

# ============================================================
# CONFIGURATION
# ============================================================
YUAFENG_KEY = os.environ.get("YUAFENG_API_KEY", "ed025d324019dab56e9094e1650626021db944e6907939f34fc172d3c6f9e5bf")

BASE_URL = "http://api-v2.yuafeng.cn/API"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

# Platform to endpoint mapping
PLATFORM_ENDPOINTS = {
    "wy": "qqmusic.php",   # NetEase (routed through QQ Music)
    "qq": "qqmusic.php",   # QQ Music
    "kg": "qqmusic.php",   # Kugou
    "kw": "qqmusic.php",   # Kuwo
    "tx": "qqmusic.php",   # Tencent
    "mg": "mgmusic.php",   # Migu
}


def _check_key() -> str:
    if not YUAFENG_KEY:
        raise RuntimeError(
            "Yuafeng API key not configured.\n"
            "1. Register at http://api-v2.yuafeng.cn (free)\n"
            "2. Set: set YUAFENG_API_KEY=your_key"
        )
    return YUAFENG_KEY


def search_music(keyword: str, source: str = "wy", limit: int = 1) -> list:
    """Search for music.

    Args:
        keyword: Search query (song name + artist works best)
        source: Platform ('wy', 'qq', 'kg', 'kw', 'mg')
        limit: Number of results (1-10)

    Returns:
        List of dicts with: song, singer, mid, music(url), cover, album_name
    """
    apikey = _check_key()
    endpoint = PLATFORM_ENDPOINTS.get(source, "qqmusic.php")
    
    params = {"msg": keyword, "n": str(min(limit, 10)), "apikey": apikey}
    r = requests.get(f"{BASE_URL}/{endpoint}", params=params, headers=HEADERS, timeout=15)
    data = r.json()
    
    if data.get("code") != 0:
        raise RuntimeError(f"Search failed: {data.get('msg', data)}")
    
    item = data.get("data", {})
    if not item or not item.get("music"):
        return []
    
    return [{
        "song": item.get("song", ""),
        "singer": item.get("singer", ""),
        "mid": item.get("mid", ""),
        "music": item.get("music", ""),
        "cover": item.get("cover", ""),
        "album_name": item.get("album_name", ""),
        "file_name": item.get("file_name", ""),
        "lyric": item.get("lyric", ""),
    }]


def get_download_url_by_name(song_name: str, artist: str = "",
                              source: str = "wy") -> Optional[dict]:
    """Get download URL by song name and artist.

    Args:
        song_name: Song name
        artist: Artist name (optional, improves accuracy)
        source: Platform

    Returns:
        dict with music(url), song, singer, file_name etc, or None if not found
    """
    apikey = _check_key()
    endpoint = PLATFORM_ENDPOINTS.get(source, "qqmusic.php")
    
    # Build query: "artist song_name" for better matching
    if artist:
        query = f"{artist} {song_name}"
    else:
        query = song_name
    
    params = {"msg": query, "n": "1", "apikey": apikey}
    r = requests.get(f"{BASE_URL}/{endpoint}", params=params, headers=HEADERS, timeout=15)
    data = r.json()
    
    if data.get("code") != 0:
        return None
    
    item = data.get("data", {})
    if not item or not item.get("music"):
        return None
    
    return {
        "song": item.get("song", ""),
        "singer": item.get("singer", ""),
        "mid": item.get("mid", ""),
        "music": item.get("music", ""),
        "cover": item.get("cover", ""),
        "album_name": item.get("album_name", ""),
        "file_name": item.get("file_name", ""),
        "lyric": item.get("lyric", ""),
    }


def download_song_by_name(song_name: str, artist: str = "",
                          output_dir: str = "downloads",
                          source: str = "wy") -> str:
    """Download a song by name via yuafeng API.

    Args:
        song_name: Song name
        artist: Artist name
        output_dir: Output directory
        source: Platform

    Returns:
        File path of the downloaded file
    """
    info = get_download_url_by_name(song_name, artist, source)
    if not info:
        raise RuntimeError(f"Cannot find download URL for: {artist} - {song_name}")
    
    os.makedirs(output_dir, exist_ok=True)
    
    # Determine file extension from URL, filename, or content-type
    url = info["music"]
    file_name = info.get("file_name", "")

    # Priority 1: Check URL for format hints
    ext = ".m4a"  # default
    url_lower = url.lower()
    if ".flac" in url_lower:
        ext = ".flac"
    elif ".mp3" in url_lower:
        ext = ".mp3"
    elif ".wav" in url_lower:
        ext = ".wav"
    elif ".ogg" in url_lower:
        ext = ".ogg"
    elif ".aac" in url_lower:
        ext = ".aac"
    # Priority 2: Check filename
    elif file_name:
        ext_match = re.search(r'\.(m4a|mp3|flac|wav|ogg|aac)', file_name.lower())
        if ext_match:
            ext = ext_match.group(0)
    
    # Build safe filename
    safe_name = "".join(c for c in f"{info['singer']} - {info['song']}" if c not in r'<>:"/\|?*')
    filepath = os.path.join(output_dir, f"{safe_name}{ext}")
    
    # Avoid overwriting
    counter = 1
    while os.path.exists(filepath):
        filepath = os.path.join(output_dir, f"{safe_name}_{counter}{ext}")
        counter += 1
    
    # Download
    url = info["music"]
    print(f"  Downloading (yuafeng): {safe_name}")
    r = requests.get(url, headers=HEADERS, timeout=120, stream=True)
    r.raise_for_status()
    
    total = int(r.headers.get("content-length", 0))
    downloaded = 0
    with open(filepath, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    print(f"\r  {pct}%", end="", flush=True)
    
    print(f"\r  Done: {safe_name} ({total/1024/1024:.1f}MB)")
    return filepath


if __name__ == "__main__":
    print("=== Yuafeng API Test ===")
    print(f"Key: {'configured' if YUAFENG_KEY else 'MISSING'}")
    
    # Search test
    print("\nSearch: Beyond 海阔天空")
    results = search_music("Beyond 海阔天空")
    for r in results:
        print(f"  {r['singer']} - {r['song']}")
        print(f"  URL: {r['music'][:80]}...")
    
    # Download test
    if results:
        print("\nDownload test...")
        fp = download_song_by_name("海阔天空", "Beyond", "test_yuafeng")
        print(f"  Saved: {fp}")
        
        import shutil
        if os.path.exists("test_yuafeng"):
            shutil.rmtree("test_yuafeng")