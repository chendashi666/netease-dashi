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

import requests
from Crypto.Cipher import AES


BASE_URL = "https://music.znnu.com"
DOMAIN = "music.znnu.com"
HMAC_KEY = "a09d0f3700a279584e1515354fbe08a7ee1c617f919543142fa625b82f1b5ad0"
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

    Args:
        link: Playlist URL or ID

    Returns:
        dict with keys: type, id, name, cover, creator, trackCount, tracks
    """
    raw_url = link if "://" in link else f"https://music.163.com/playlist?id={link}"
    link_type, playlist_id = _parse_link(raw_url)
    if link_type != "playlist":
        raise ValueError(f"Expected playlist link, got {link_type}")

    ip = _fetch_ip()
    params = {
        "act": "playlist",
        "id": playlist_id,
        "rawInput": raw_url,
        "ip": ip,
    }

    resp = _api_post("/api/playlist", params)
    if resp.get("code") != 200:
        raise RuntimeError(f"Playlist parse failed: {resp.get('msg', resp)}")

    data = resp["data"]
    return {
        "type": "playlist",
        "id": data.get("id"),
        "name": data.get("name"),
        "cover": data.get("cover"),
        "creator": data.get("creator"),
        "trackCount": data.get("trackCount", len(data.get("tracks", []))),
        "tracks": data.get("tracks", []),
    }


def get_album(link: str) -> dict:
    """Get album info including all tracks."""
    raw_url = link if "://" in link else f"https://music.163.com/album?id={link}"
    link_type, album_id = _parse_link(raw_url)
    if link_type != "album":
        raise ValueError(f"Expected album link, got {link_type}")

    ip = _fetch_ip()
    params = {
        "act": "album",
        "id": album_id,
        "rawInput": raw_url,
        "ip": ip,
    }

    resp = _api_post("/api/album", params)
    if resp.get("code") != 200:
        raise RuntimeError(f"Album parse failed: {resp.get('msg', resp)}")

    data = resp["data"]
    return {
        "type": "album",
        "id": data.get("id"),
        "name": data.get("name"),
        "cover": data.get("cover"),
        "artist": data.get("artist"),
        "trackCount": data.get("trackCount", len(data.get("tracks", []))),
        "tracks": data.get("tracks", []),
    }


def get_song_url(song_id, level: str = "lossless", raw_input: str = "") -> dict:
    """Get download URL for a single song.

    Args:
        song_id: Song ID (string or int)
        level: Quality level - 'lossless', 'hires', 'exhigh', 'higher', 'standard'
        raw_input: Original input link

    Returns:
        dict with keys: id, name, artist, album, cover, url, type, level, size, lrc
    """
    song_id = str(song_id)
    if not raw_input:
        raw_input = f"https://music.163.com/song?id={song_id}"

    ip = _fetch_ip()
    params = {
        "act": "song",
        "id": song_id,
        "level": level,
        "rawInput": raw_input,
        "ip": ip,
    }

    resp = _api_post("/api/song", params)
    if resp.get("code") != 200:
        raise RuntimeError(f"Song URL fetch failed: {resp.get('msg', resp)}")

    data = resp["data"]
    if not data.get("url"):
        raise RuntimeError(
            f"Song '{data.get('name', song_id)}' not available for download. "
            f"May be VIP-only or region-restricted."
        )

    return data


def _safe_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    unsafe = r'<>:"/\|?*'
    for ch in unsafe:
        name = name.replace(ch, "_")
    return name.strip().strip(".") or "unknown"


def download_song(song_id, output_dir: str = "downloads",
                  level: str = "lossless",
                  raw_input: str = "") -> str:
    """Download a single song and return the output file path.

    Args:
        song_id: Song ID
        output_dir: Directory to save files
        level: Quality level
        raw_input: Original input link

    Returns:
        Path to the downloaded file
    """
    info = get_song_url(song_id, level=level, raw_input=raw_input)

    song_name = info.get("name", song_id)
    artist = info.get("artist", "Unknown")
    ext = info.get("type", "flac")

    filename = _safe_filename(f"{artist} - {song_name}.{ext}")
    os.makedirs(output_dir, exist_ok=True)

    # Ensure unique filename
    filepath = os.path.join(output_dir, filename)
    base, suffix = os.path.splitext(filepath)
    counter = 1
    while os.path.exists(filepath):
        filepath = f"{base} ({counter}){suffix}"
        counter += 1

    url = info["url"]
    print(f"  Downloading: {artist} - {song_name} ({info.get('size', '?')}) ... ",
          end="", flush=True)

    r = requests.get(url, headers=HEADERS_BASE, timeout=300, stream=True)
    r.raise_for_status()
    total = int(r.headers.get("content-length", 0))

    with open(filepath, "wb") as f:
        downloaded = 0
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = downloaded * 100 // total
                print(f"\r  Downloading: {artist} - {song_name} ... {pct}%",
                      end="", flush=True)

    print(f"\r  Done: {artist} - {song_name} ({os.path.getsize(filepath)/1024/1024:.1f}MB)")
    return filepath


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
            filepath = download_song(song_id, output_dir, level=level, raw_input=link)
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
            filepath = download_song(song_id, output_dir, level=level, raw_input=link)
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
