#!/usr/bin/env python3
"""NetEase Cloud Music link parser and downloader.

Supports playlist, album, and single song URLs.
Uses music.znnu.com API as a proxy to handle NetEase's encrypted API.
"""

import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.parse
import base64
from typing import Optional

# Multi-source fallback (tries all available music APIs)
import music_sources

import requests
from Crypto.Cipher import AES


BASE_URL = "https://music.znnu.com"
DOMAIN = "music.znnu.com"
HMAC_KEY = "a09d0f3700a279584e1515354fbe08a7ee1c617f919543142fa625b82f1b5ad0"
# NetEase direct API headers (for playlist/album/song info)
HEADERS_NETEASE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://music.163.com",
}

HEADERS_BASE = {
    "X-Referer": "musicParser",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

# Session-level cache
_cache = {"key_token": None, "key_raw": None, "expire_at": 0, "ip": None}


def _fetch_key() -> tuple:
    """Fetch and cache the API key and key token."""
    now = int(time.time())
    if _cache["key_token"] and _cache["expire_at"] - 5 > now:
        return _cache["key_token"], _cache["key_raw"]

    r = requests.get(f"{BASE_URL}/api/key", headers=HEADERS_BASE, timeout=15)
    data = r.json()
    if data.get("code") != 200:
        raise RuntimeError(f"Failed to get API key: {data.get('msg', data)}")

    kd = data["data"]
    _cache["key_token"] = kd["keyToken"]
    _cache["key_raw"] = base64.b64decode(kd["key"])
    _cache["expire_at"] = kd["expireAt"]
    return _cache["key_token"], _cache["key_raw"]


def _fetch_ip() -> str:
    """Fetch the client IP (used in API signatures)."""
    if _cache["ip"]:
        return _cache["ip"]
    try:
        r = requests.get(f"{BASE_URL}/api/ip", headers=HEADERS_BASE, timeout=10)
        _cache["ip"] = r.json().get("ip", "0.0.0.0")
    except Exception:
        _cache["ip"] = "0.0.0.0"
    return _cache["ip"]


def _make_signature(params: dict, timestamp: int) -> str:
    """Generate HMAC-SHA256 signature for API requests."""
    keys = sorted(params.keys())
    sign_string = str(timestamp) + DOMAIN
    for k in keys:
        sign_string += k + "=" + str(params[k])
    return hmac.new(
        HMAC_KEY.encode(), sign_string.encode(), hashlib.sha256
    ).hexdigest()


def _api_post(endpoint: str, params: dict) -> dict:
    """Make an authenticated POST request to the znnu.com API."""
    key_token, key_raw = _fetch_key()
    ts = int(time.time())

    signature = _make_signature(params, ts)
    body = urllib.parse.urlencode(params)
    body += f"&signature={signature}&timestamp={ts}&domain={DOMAIN}"

    headers = {
        **HEADERS_BASE,
        "X-Key-Token": key_token,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    r = requests.post(
        f"{BASE_URL}{endpoint}", data=body, headers=headers, timeout=30
    )
    data = r.json()

    # Decrypt response if encrypted
    if data.get("code") == 200 and data.get("data", {}).get("enc") == 1:
        enc = data["data"]
        iv = base64.b64decode(enc["iv"])
        ciphertext = base64.b64decode(enc["ciphertext"])
        tag = base64.b64decode(enc.get("tag", ""))
        cipher = AES.new(key_raw, AES.MODE_GCM, nonce=iv)
        plaintext = cipher.decrypt_and_verify(ciphertext, tag)
        data["data"] = json.loads(plaintext.decode("utf-8"))

    return data


def _parse_link(link: str) -> tuple:
    """Parse a NetEase Cloud Music link to determine type and ID.

    Returns:
        (type, id) where type is 'playlist', 'album', or 'song'
    """
    link = link.strip()

    # Direct numeric ID
    if re.match(r"^\d+$", link):
        return "song", link

    # Short link
    short_match = re.search(r"163cn\.tv/([a-zA-Z0-9]+)", link)
    if short_match:
        try:
            r = requests.get(link, allow_redirects=False, timeout=10, headers=HEADERS_BASE)
            location = r.headers.get("Location", "")
            if location:
                return _parse_link(location)
        except Exception:
            pass

    # Standard URL patterns
    patterns = [
        (r"/playlist\?id=(\d+)", "playlist"),
        (r"/m/playlist\?id=(\d+)", "playlist"),
        (r"/playlist/(\d+)", "playlist"),
        (r"/album\?id=(\d+)", "album"),
        (r"/m/album\?id=(\d+)", "album"),
        (r"/album/(\d+)", "album"),
        (r"/song\?id=(\d+)", "song"),
        (r"/m/song\?id=(\d+)", "song"),
        (r"/song/(\d+)", "song"),
    ]

    for pattern, link_type in patterns:
        match = re.search(pattern, link)
        if match:
            return link_type, match.group(1)

    raise ValueError(f"Cannot parse link: {link}. Supported formats:\n"
                     "  https://music.163.com/playlist?id=XXXX\n"
                     "  https://music.163.com/album?id=XXXX\n"
                     "  https://music.163.com/song?id=XXXX\n"
                     "  Or just a numeric ID")


def get_playlist(link: str) -> dict:
    """Get playlist info including all tracks.

    Uses v6 API to get full track list, then batch-fetches song details.
    """
    raw_url = link if "://" in link else f"https://music.163.com/playlist?id={link}"
    link_type, playlist_id = _parse_link(raw_url)
    if link_type != "playlist":
        raise ValueError(f"Expected playlist link, got {link_type}")

    errors = []

    # Method 1: v6 API (gets full trackIds, then batch fetch details)
    try:
        r = requests.get(
            f"https://music.163.com/api/v6/playlist/detail?id={playlist_id}",
            headers=HEADERS_NETEASE,
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("code") == 200 and data.get("playlist"):
                pl = data["playlist"]
                track_ids = pl.get("trackIds", [])
                total_count = pl.get("trackCount", len(track_ids))

                if track_ids:
                    tracks = []
                    batch_size = 100
                    for i in range(0, len(track_ids), batch_size):
                        batch = track_ids[i:i + batch_size]
                        ids_str = ",".join(str(x["id"]) for x in batch)
                        if i > 0:
                            time.sleep(0.3)
                        try:
                            r2 = requests.get(
                                f"https://music.163.com/api/song/detail?ids=[{ids_str}]",
                                headers=HEADERS_NETEASE,
                                timeout=15,
                            )
                            if r2.status_code == 200:
                                d2 = r2.json()
                                if d2.get("code") == 200:
                                    for s in d2.get("songs", []):
                                        artists_list = s.get("artists") or []
                                        artists = ", ".join(
                                            a.get("name", "?") for a in artists_list
                                        )
                                        tracks.append({
                                            "id": s["id"],
                                            "name": s.get("name", "?"),
                                            "artists": artists,
                                            "album": (s.get("album") or {}).get("name", ""),
                                            "duration": s.get("dt", 0),
                                        })
                        except Exception:
                            continue

                    if tracks:
                        if len(tracks) < len(track_ids):
                            print(f"  Warning: Got {len(tracks)}/{len(track_ids)} tracks")
                        return {
                            "type": "playlist",
                            "id": pl.get("id"),
                            "name": pl.get("name", ""),
                            "cover": pl.get("coverImgUrl", ""),
                            "creator": (pl.get("creator") or {}).get("nickname", ""),
                            "trackCount": total_count,
                            "tracks": tracks,
                        }
                    else:
                        errors.append("v6 batch: no tracks fetched")
    except Exception as e:
        errors.append(f"v6 API: {e}")

    # Method 2: Standard API (may only return partial tracks)
    try:
        r = requests.get(
            f"https://music.163.com/api/playlist/detail?id={playlist_id}",
            headers=HEADERS_NETEASE,
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("code") == 200:
                result = data["result"]
                tracks = []
                for t in result.get("tracks", []):
                    try:
                        artists = ", ".join(a.get("name", "?") for a in (t.get("artists") or []))
                        tracks.append({
                            "id": t["id"],
                            "name": t["name"],
                            "artists": artists,
                            "album": (t.get("album") or {}).get("name", ""),
                            "duration": t.get("duration", 0),
                        })
                    except (KeyError, TypeError):
                        continue
                tc = result.get("trackCount", len(tracks))
                if tc > len(tracks):
                    print(f"  Warning: Only got {len(tracks)}/{tc} tracks via standard API")
                return {
                    "type": "playlist",
                    "id": result.get("id"),
                    "name": result.get("name"),
                    "cover": result.get("coverImgUrl", ""),
                    "creator": result.get("creator", {}).get("nickname", ""),
                    "trackCount": tc,
                    "tracks": tracks,
                }
    except (requests.RequestException, ValueError, KeyError) as e:
        errors.append(f"Standard API: {e}")

    # Method 3: znnu.com proxy
    try:
        ip = _fetch_ip()
        params = {
            "act": "playlist",
            "id": playlist_id,
            "rawInput": raw_url,
            "ip": ip,
        }
        resp = _api_post("/api/playlist", params)
        if resp.get("code") == 200:
            data = resp["data"]
            tracks = []
            for t in data.get("tracks", []):
                try:
                    tracks.append({
                        "id": t["id"],
                        "name": t.get("name", "?"),
                        "artists": t.get("artists", "?"),
                        "album": t.get("album", ""),
                        "duration": t.get("duration", 0),
                    })
                except (KeyError, TypeError):
                    continue
            return {
                "type": "playlist",
                "id": data.get("id"),
                "name": data.get("name", ""),
                "cover": data.get("cover", ""),
                "creator": data.get("creator", ""),
                "trackCount": data.get("trackCount", len(tracks)),
                "tracks": tracks,
            }
    except Exception as e:
        errors.append(f"znnu.com: {e}")

    raise RuntimeError(
        f"Failed to fetch playlist {playlist_id}.\n"
        f"Errors: {'; '.join(errors)}"
    )

def get_album(link: str) -> dict:
    """Get album info including all tracks."""
    raw_url = link if "://" in link else f"https://music.163.com/album?id={link}"
    link_type, album_id = _parse_link(raw_url)
    if link_type != "album":
        raise ValueError(f"Expected album link, got {link_type}")

    # Try NetEase direct API first
    try:
        r = requests.get(
            f"https://music.163.com/api/album/{album_id}",
            headers=HEADERS_NETEASE,
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("code") == 200:
                album = data["album"]
                tracks = []
                for t in album.get("songs", []):
                    try:
                        artists = ", ".join(a.get("name", "?") for a in (t.get("artists") or []))
                        tracks.append({
                            "id": t["id"],
                            "name": t["name"],
                            "artists": artists,
                            "duration": t.get("duration", 0),
                        })
                    except (KeyError, TypeError):
                        continue
                artist_name = album.get("artist", {}).get("name", "") if isinstance(album.get("artist"), dict) else album.get("artist", "")
                return {
                    "type": "album",
                    "id": album.get("id"),
                    "name": album.get("name"),
                    "cover": album.get("picUrl", ""),
                    "artist": artist_name,
                    "trackCount": album.get("size", len(tracks)),
                    "tracks": tracks,
                }
    except (requests.RequestException, ValueError, KeyError):
        pass

    # Fallback: znnu.com proxy
    errors = []
    try:
        ip = _fetch_ip()
        params = {
            "act": "album",
            "id": album_id,
            "rawInput": raw_url,
            "ip": ip,
        }
        resp = _api_post("/api/album", params)
        if resp.get("code") == 200:
            data = resp["data"]
            return {
                "type": "album",
                "id": data.get("id"),
                "name": data.get("name"),
                "cover": data.get("cover"),
                "artist": data.get("artist", ""),
                "trackCount": data.get("trackCount", len(data.get("tracks", []))),
                "tracks": data.get("tracks", []),
            }
        errors.append(f"znnu.com: {resp.get('msg', 'unknown')}")
    except Exception as e:
        errors.append(f"znnu.com: {e}")

    raise RuntimeError(
        f"Album fetch failed. NetEase album API requires login.\n"
        f"The proxy service (music.znnu.com) is also currently unavailable.\n"
        f"Please try again later."
    )


def _get_song_url_netease(song_id, level: str = "lossless"):
    """Try to get download URL from NetEase old API (no encryption needed).

    Only works for non-VIP songs (fee != 1).
    Returns dict with url/type/size or raises exception.
    """
    # Map quality levels to bitrates
    bitrate_map = {
        "standard": 128000,
        "higher": 192000,
        "exhigh": 320000,
        "hires": 999000,
        "lossless": 999000,
    }
    br = bitrate_map.get(level, 320000)

    if _has_netease_cookie():
        from netease_weapi import _get_session as _weapi_session
        session = _weapi_session()
    else:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://music.163.com",
        })

    # Get song info first
    r_info = session.get(
        f"https://music.163.com/api/song/detail?ids=[{song_id}]",
        timeout=10,
    )
    if r_info.status_code != 200:
        raise RuntimeError("Failed to fetch song info from NetEase")
    info_data = r_info.json()
    if info_data.get("code") != 200 or not info_data.get("songs"):
        raise RuntimeError("Song not found on NetEase")
    song = info_data["songs"][0]

    # Check if song is downloadable
    fee = song.get("fee", -1)
    if fee in (1, 4) and not _has_netease_cookie():
        raise RuntimeError(
            f"Song '{song['name']}' is VIP-only and cannot be downloaded.\n"
            f"Set a NetEase cookie to enable VIP FLAC downloads.\n"
            f"Or try: python main.py cookie set \"MUSIC_U=YOUR_VALUE\""
        )
    if fee in (1, 4) and _has_netease_cookie():
        print(f"  (VIP song, using login cookie)")

    # Get download URL
    r_url = session.get(
        f"https://music.163.com/api/song/enhance/player/url?id={song_id}&ids=[{song_id}]&br={br}",
        timeout=15,
    )
    url_data = r_url.json()
    if url_data.get("code") != 200 or not url_data.get("data"):
        raise RuntimeError("Failed to get download URL from NetEase")

    dl = url_data["data"][0]
    if not dl.get("url"):
        # Try lower quality
        for fallback_br in [320000, 192000, 128000]:
            if fallback_br == br:
                continue
            r_fb = session.get(
                f"https://music.163.com/api/song/enhance/player/url?id={song_id}&ids=[{song_id}]&br={fallback_br}",
                timeout=10,
            )
            fb_data = r_fb.json()
            if fb_data.get("code") == 200 and fb_data.get("data"):
                fb_dl = fb_data["data"][0]
                if fb_dl.get("url"):
                    dl = fb_dl
                    break
        else:
            raise RuntimeError(
                f"Song '{song['name']}' download URL not available.\n"
                f"The song may be region-restricted or requires VIP.\n"
                f"Fee status: {fee}"
            )

    artists = ", ".join(a.get("name", "") for a in song.get("artists", []))
    return {
        "id": song["id"],
        "name": song["name"],
        "artist": artists,
        "album": (song.get("album") or {}).get("name", ""),
        "cover": (song.get("album") or {}).get("picUrl", ""),
        "url": dl["url"],
        "type": dl.get("type", "mp3"),
        "level": level,
        "size": dl.get("size", 0),
    }



# ============================================================
# Yuafeng API integration (for VIP songs)
# ============================================================
def _get_song_url_yuafeng(song_id, level: str = "lossless"):
    """Try to get download URL from yuafeng.cn API (supports VIP songs).

    First gets song name/artist from NetEase, then searches yuafeng by name.
    Requires YUAFENG_API_KEY env var or yuafeng_api.YUAFENG_KEY.
    Register for free at http://api-v2.yuafeng.cn
    """
    try:
        from yuafeng_api import get_download_url_by_name, YUAFENG_KEY
        if not YUAFENG_KEY:
            return None

        # Get song info from NetEase first (name + artist needed for yuafeng search)
        song_name = None
        artist = None
        try:
            r = requests.get(
                f"https://music.163.com/api/song/detail?ids=[{song_id}]",
                headers=HEADERS_NETEASE,
                timeout=10,
            )
            nd = r.json()
            if nd.get("code") == 200 and nd.get("songs"):
                song = nd["songs"][0]
                song_name = song["name"]
                artists_list = song.get("artists", [])
                if artists_list:
                    artist = artists_list[0].get("name", "")
        except Exception:
            pass

        if not song_name:
            return None

        # Search yuafeng by name + artist
        info = get_download_url_by_name(song_name, artist or "", source="wy")
        if info and info.get("music"):
            # Determine file type from URL
            url = info["music"]
            file_type = "m4a"
            if ".mp3" in url.lower():
                file_type = "mp3"
            elif ".flac" in url.lower():
                file_type = "flac"

            return {
                "id": song_id,
                "name": info.get("song", song_name),
                "artist": info.get("singer", artist or ""),
                "album": info.get("album_name", ""),
                "cover": info.get("cover", ""),
                "url": url,
                "type": file_type,
                "level": level,
                "size": 0,  # Will be determined during download
            }
    except Exception:
        pass
    return None


def get_song_url(song_id, level: str = "lossless", raw_input: str = "") -> dict:
    """Get download URL for a single song.

    Tries in order:
      1. NetEase old API (works for free/non-VIP songs)
      2. NetEase weapi + cookie (VIP songs when logged in)
      3. yuafeng.cn API (multi-platform fallback)
      4. znnu.com proxy (for VIP songs when proxy is online)
    """
    song_id = str(song_id)
    if not raw_input:
        raw_input = f"https://music.163.com/song?id={song_id}"

    errors = []

    # Try NetEase old API first (works for free/non-VIP songs)
    try:
        return _get_song_url_netease(song_id, level)
    except Exception as e:
        errors.append(f"NetEase direct: {e}")

    # Try NetEase weapi + cookie (for VIP songs when logged in)
    try:
        from netease_weapi import has_cookie, get_song_download_url as weapi_dl
        if has_cookie():
            result = weapi_dl(song_id, level)
            if result and result.get("url"):
                # Map to expected format
                return {
                    "id": result.get("id", song_id),
                    "name": "",  # Will be filled by caller
                    "artist": "",
                    "album": "",
                    "url": result["url"],
                    "type": result.get("type", "flac"),
                    "level": level,
                    "size": result.get("size", 0),
                }
            elif result:
                errors.append(f"NetEase weapi: no URL (code={result.get('code', '?')})")
    except Exception as e:
        errors.append(f"NetEase weapi: {e}")

    # Try yuafeng.cn API (for VIP songs, requires API key)
    yuafeng_result = _get_song_url_yuafeng(song_id, level)
    if yuafeng_result and yuafeng_result.get("url"):
        return yuafeng_result
    if yuafeng_result is not None:
        errors.append("yuafeng: no URL returned (check API key or song availability)")

    # Fallback: znnu.com proxy (for VIP songs when proxy is online)
    try:
        ip = _fetch_ip()
        params = {
            "act": "song",
            "id": song_id,
            "level": level,
            "rawInput": raw_input,
            "ip": ip,
        }
        resp = _api_post("/api/song", params)
        if resp.get("code") == 200:
            data = resp["data"]
            if data.get("url"):
                return data
        errors.append(f"znnu.com: {resp.get('msg', 'unknown')}")
    except Exception as e:
        errors.append(f"znnu.com: {e}")

    # All sources failed
    raise RuntimeError(
        f"Cannot get download URL for song {song_id}.\n"
        f"Errors: {'; '.join(errors)}"
    )
def _has_netease_cookie() -> bool:
    """Check if NetEase login cookie is configured."""
    try:
        from netease_weapi import has_cookie
        return has_cookie()
    except ImportError:
        return False


def _safe_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    unsafe = r'<>:"/\|?*'
    for ch in unsafe:
        name = name.replace(ch, "_")
    return name.strip().strip(".") or "unknown"


def download_song(song_id, output_dir: str = "downloads",
                  level: str = "lossless", raw_input: str = "",
                  use_yuafeng: bool = False,
                  song_name: str = "", artist: str = "") -> str:
    """Download a single song.

    Args:
        song_id: Song ID
        output_dir: Output directory
        level: Quality level
        raw_input: Original input link
        use_yuafeng: If True, try yuafeng API for VIP songs (requires API key)

    Returns the file path of the downloaded file.

    Returns:
        Path to the downloaded file
    """
    # Try normal download flow first
    try:
        info = get_song_url(song_id, level=level, raw_input=raw_input)
        _song_name = info.get("name", song_id)
        _artist = info.get("artist", "Unknown")
        if not song_name:
            song_name = _song_name
        if not artist:
            artist = _artist
        ext = info.get("type", "flac")
        url = info["url"]

        filename = _safe_filename(f"{_artist} - {_song_name}.{ext}")
        os.makedirs(output_dir, exist_ok=True)

        # Ensure unique filename
        filepath = os.path.join(output_dir, filename)
        base, suffix = os.path.splitext(filepath)
        counter = 1
        while os.path.exists(filepath):
            filepath = f"{base} ({counter}){suffix}"
            counter += 1

        print(f"  Downloading: {_artist} - {_song_name} ({info.get('size', '?')} ... ",
              end="", flush=True)

        r = requests.get(url, headers=HEADERS_BASE, timeout=300, stream=True)
        r.raise_for_status()

        # Use Content-Type header to detect actual format
        content_type = r.headers.get("content-type", "").lower()
        ct_map = {"audio/flac": "flac", "audio/mpeg": "mp3", "audio/mp4": "m4a",
                   "audio/x-m4a": "m4a", "audio/wav": "wav", "audio/wave": "wav",
                   "audio/ogg": "ogg", "audio/aac": "aac"}
        for ct_key, ct_ext in ct_map.items():
            if ct_key in content_type:
                ext = ct_ext
                # Correct file extension if needed
                new_filepath = os.path.join(output_dir, _safe_filename(f"{_artist} - {_song_name}.{ext}"))
                if new_filepath != filepath:
                    filepath = new_filepath
                    counter = 1
                    base, suffix = os.path.splitext(filepath)
                    while os.path.exists(filepath):
                        filepath = f"{base} ({counter}){suffix}"
                        counter += 1
                break

        total = int(r.headers.get("content-length", 0))

        with open(filepath, "wb") as f:
            downloaded = 0
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    print(f"\r  Downloading: {_artist} - {_song_name} ... {pct}%",
                          end="", flush=True)

        print(f"\r  Done: {_artist} - {_song_name} ({os.path.getsize(filepath)/1024/1024:.1f}MB)")
        return filepath

    except Exception as e:
        # Normal download failed - try multi-source fallback
        if not song_name:
            song_name = str(song_id)
        if not artist:
            artist = "Unknown"

        print(f"  Primary download failed: {e}")
        print(f"  Falling back to multi-source search...")

        # Try yuafeng API with multiple platforms
        from music_sources import download_with_fallback
        fallback_path = download_with_fallback(song_name, artist, output_dir, level=level)
        if fallback_path:
            return fallback_path

        raise RuntimeError(
            f"All download sources failed for '{artist} - {song_name}'.\n"
            f"Primary error: {e}"
        )


def download_playlist(link: str, output_dir: str = "downloads",
                      level: str = "lossless") -> list:
    """Download all songs from a playlist.

    Args:
        link: Playlist URL or ID
        output_dir: Directory to save files
        level: Quality level

    Returns:
        List of downloaded file paths
    """
    playlist = get_playlist(link)
    tracks = playlist["tracks"]
    total = len(tracks)

    print(f"\nPlaylist: {playlist['name']}")
    print(f"Tracks: {total}")
    print(f"Quality: {level}")
    print(f"Output: {os.path.abspath(output_dir)}")
    print("-" * 60)

    results = []
    failed = []
    for i, track in enumerate(tracks, 1):
        song_id = str(track["id"])
        song_name = track.get("name", song_id)
        artist = track.get("artists", "Unknown")

        print(f"\n[{i}/{total}] {artist} - {song_name}")
        try:
            filepath = download_song(song_id, output_dir, level=level, raw_input=link, song_name=song_name, artist=artist)
            results.append(filepath)
        except Exception as e:
            print(f"  FAILED: {e}")
            failed.append((song_id, song_name, str(e)))

    print(f"\n{'=' * 60}")
    print(f"Done! {len(results)} downloaded, {len(failed)} failed.")
    if failed:
        print("Failed songs:")
        for sid, sname, err in failed:
            print(f"  - {sname} (id={sid}): {err}")

    return results


def download_album(link: str, output_dir: str = "downloads",
                   level: str = "lossless") -> list:
    """Download all songs from an album."""
    album = get_album(link)
    tracks = album["tracks"]
    total = len(tracks)

    print(f"\nAlbum: {album['name']} - {album.get('artist', 'Unknown')}")
    print(f"Tracks: {total}")
    print(f"Quality: {level}")
    print(f"Output: {os.path.abspath(output_dir)}")
    print("-" * 60)

    results = []
    failed = []
    for i, track in enumerate(tracks, 1):
        song_id = str(track["id"])
        song_name = track.get("name", song_id)
        artist = track.get("artists", "Unknown")

        print(f"\n[{i}/{total}] {artist} - {song_name}")
        try:
            filepath = download_song(song_id, output_dir, level=level, raw_input=link, song_name=song_name, artist=artist)
            results.append(filepath)
        except Exception as e:
            print(f"  FAILED: {e}")
            failed.append((song_id, song_name, str(e)))

    print(f"\n{'=' * 60}")
    print(f"Done! {len(results)} downloaded, {len(failed)} failed.")
    if failed:
        print("Failed songs:")
        for sid, sname, err in failed:
            print(f"  - {sname} (id={sid}): {err}")

    return results


AVAILABLE_LEVELS = ["lossless", "hires", "exhigh", "higher", "standard"]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="NetEase Cloud Music link parser & downloader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python netease_parser.py "https://music.163.com/playlist?id=9426599671"
  python netease_parser.py "https://music.163.com/song?id=255574"
  python netease_parser.py --level hires "https://music.163.com/album?id=123"
  python netease_parser.py --output ./my_music --level standard "SONG_ID"
        """,
    )
    parser.add_argument("link", help="NetEase Cloud Music link or numeric ID")
    parser.add_argument("-o", "--output", default="downloads",
                        help="Output directory (default: downloads)")
    parser.add_argument("-l", "--level", default="lossless",
                        choices=AVAILABLE_LEVELS,
                        help="Audio quality level (default: lossless)")
    parser.add_argument("--info-only", action="store_true",
                        help="Only show track info, don't download")

    args = parser.parse_args()

    try:
        link_type, _ = _parse_link(args.link)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    try:
        if link_type == "playlist":
            if args.info_only:
                pl = get_playlist(args.link)
                print(f"\nPlaylist: {pl['name']}")
                print(f"Creator: {pl.get('creator', 'Unknown')}")
                print(f"Tracks: {pl['trackCount']}")
                print("-" * 50)
                for i, t in enumerate(pl["tracks"], 1):
                    print(f"  {i:3d}. {t.get('artists', '?')} - {t['name']}")
            else:
                download_playlist(args.link, args.output, args.level)

        elif link_type == "album":
            if args.info_only:
                al = get_album(args.link)
                print(f"\nAlbum: {al['name']}")
                print(f"Artist: {al.get('artist', 'Unknown')}")
                print(f"Tracks: {al['trackCount']}")
                print("-" * 50)
                for i, t in enumerate(al["tracks"], 1):
                    print(f"  {i:3d}. {t.get('artists', '?')} - {t['name']}")
            else:
                download_album(args.link, args.output, args.level)

        elif link_type == "song":
            song_id = _parse_link(args.link)[1]
            if args.info_only:
                info = get_song_url(song_id, level=args.level, raw_input=args.link)
                print(f"\nSong: {info.get('artist', '?')} - {info['name']}")
                print(f"Album: {info.get('album', '?')}")
                print(f"Quality: {info.get('level', '?')}")
                print(f"Format: {info.get('type', '?')}")
                print(f"Size: {info.get('size', '?')}")
                print(f"URL: {info.get('url', 'N/A')[:80]}...")
            else:
                filepath = download_song(song_id, args.output,
                                         level=args.level,
                                         raw_input=args.link)
                print(f"\nSaved to: {filepath}")

    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
