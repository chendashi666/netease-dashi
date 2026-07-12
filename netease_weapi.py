# -*- coding: utf-8 -*-
"""NetEase Cloud Music weapi encryption module.

Implements the weapi encryption protocol used by NetEase's web API.
This allows calling NetEase's official API for download URLs,
including lossless/FLAC quality (when available).

Reference: Binaryify/NeteaseCloudMusicApi (Node.js)
"""

import base64
import hashlib
import json
import os
import random
import string
import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from typing import Optional

# ============================================================
# Constants
# ============================================================

# NetEase RSA public key (hex encoded)
RSA_PUBLIC_KEY_HEX = (
    "e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725"
    "152b3ab0b7f583a91ad4e06f1198731c8fb4061e6e492d6027a179464b983aa3"
    "4d9c7bc92ca4c00320389845aff83145f18d6315b2ad7a835a00cb11548ea315"
    "626eb42a4908eb44f95417e854d56530c70416c5fa7677259b14966e81def1cccd"
)

# AES IV for weapi (fixed)
WEAPI_IV = b"0102030405060708"

# Base URLs
BASE_URL = "https://music.163.com"

# Default headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://music.163.com",
    "Content-Type": "application/x-www-form-urlencoded",
}

# Cookie for VIP songs (set via env var NETEASE_COOKIE or login)
# Cookie file path (for persistent storage)
COOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "netease_cookie.txt")

NETEASE_COOKIE = os.environ.get("NETEASE_COOKIE", "")

# Try loading from file if not in env
if not NETEASE_COOKIE and os.path.exists(COOKIE_FILE):
    try:
        with open(COOKIE_FILE, "r", encoding="utf-8") as f:
            NETEASE_COOKIE = f.read().strip()
    except Exception:
        pass

_session = None


def set_cookie(cookie_str: str, save: bool = True):
    """Set NetEase login cookie and optionally save to file.

    Call this with the MUSIC_U cookie value or full cookie string.
    Example: set_cookie("MUSIC_U=xxxxx; __csrf=yyyyy")

    Args:
        cookie_str: Cookie string from browser (MUSIC_U=...; ...)
        save: If True, save to cookie file for persistence
    """
    global NETEASE_COOKIE, _session
    NETEASE_COOKIE = cookie_str
    _session = None  # Reset session to pick up new cookie
    
    if save:
        try:
            with open(COOKIE_FILE, "w", encoding="utf-8") as f:
                f.write(cookie_str)
        except Exception:
            pass


def clear_cookie():
    """Clear the saved cookie."""
    global NETEASE_COOKIE, _session
    NETEASE_COOKIE = ""
    _session = None
    if os.path.exists(COOKIE_FILE):
        os.remove(COOKIE_FILE)


def has_cookie() -> bool:
    """Check if a cookie is configured."""
    return bool(NETEASE_COOKIE)


def is_vip() -> Optional[bool]:
    """Check if the current cookie has VIP status.

    Tests by requesting a known VIP song (Beyond 海阔天空, id=1357375695)
    and checking if NetEase returns a download URL.

    Returns:
        True if VIP, False if not VIP, None if cannot determine (no cookie or network error)
    """
    if not has_cookie():
        return None
    try:
        import requests
        session = _get_session()
        # Try to get download URL for a known VIP song
        r = session.get(
            'https://music.163.com/api/song/enhance/player/url?id=1357375695&ids=[1357375695]&br=999000',
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            if data.get('code') == 200 and data.get('data'):
                dl = data['data'][0]
                return bool(dl.get('url'))
        return False
    except Exception:
        return None


def _get_session() -> requests.Session:
    """Get or create a requests session with proper headers and cookies."""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
        if NETEASE_COOKIE:
            for item in NETEASE_COOKIE.split("; "):
                if "=" in item:
                    key, _, value = item.partition("=")
                    _session.cookies.set(key.strip(), value.strip())
    return _session


def _rsa_encrypt(data: bytes) -> str:
    """Encrypt data with NetEase's RSA public key (pure Python implementation).

    We implement RSA directly because the public key is fixed and
    the data is always small (16 bytes). Uses PKCS1 v1.5 padding.

    Args:
        data: 16-byte AES key to encrypt

    Returns:
        Hex-encoded encrypted data
    """
    # NetEase uses reversed hex public key
    n = int(RSA_PUBLIC_KEY_HEX, 16)
    e = 0x010001  # Standard RSA exponent

    # Convert data to integer with PKCS1 v1.5 padding
    k = 128  # RSA key size in bytes (1024-bit)
    data_len = len(data)

    # PKCS1 v1.5 type 2 padding
    ps_len = k - data_len - 3
    ps = bytearray()
    while len(ps) < ps_len:
        b = random.randint(1, 255)
        ps.append(b)

    padded = b"\x00\x02" + bytes(ps) + b"\x00" + data

    # Convert to integer
    padded_int = int.from_bytes(padded, "big")

    # RSA encryption: c = m^e mod n
    encrypted_int = pow(padded_int, e, n)

    # Convert to bytes, ensure 128 bytes
    encrypted_bytes = encrypted_int.to_bytes(128, "big")

    # Return as hex
    return encrypted_bytes.hex()


def _keygen() -> tuple:
    """Generate a random AES key and its RSA-encrypted form.

    Returns:
        (aes_key_bytes, enc_sec_key_hex)
    """
    # Generate random 16-byte AES key
    secret_key = "".join(random.choice(string.ascii_letters + string.digits) for _ in range(16))
    secret_key_bytes = secret_key.encode()

    # RSA encrypt the key
    enc_sec_key = _rsa_encrypt(secret_key_bytes)

    return secret_key_bytes, enc_sec_key


def weapi_encrypt(data: dict) -> dict:
    """Encrypt data using NetEase's weapi protocol.

    Args:
        data: Dictionary of API parameters

    Returns:
        dict with "params" and "encSecKey" keys
    """
    secret_key, enc_sec_key = _keygen()

    # Convert data to JSON string
    json_str = json.dumps(data)

    # AES-128-CBC encrypt with PKCS7 padding
    cipher = AES.new(secret_key, AES.MODE_CBC, WEAPI_IV)
    padded_data = pad(json_str.encode(), AES.block_size)
    encrypted = cipher.encrypt(padded_data)

    # Base64 encode
    params = base64.b64encode(encrypted).decode()

    return {"params": params, "encSecKey": enc_sec_key}


def weapi_request(endpoint: str, data: dict) -> dict:
    """Make a weapi-encrypted POST request to NetEase API.

    Args:
        endpoint: API path (e.g., "/weapi/song/enhance/player/url/v1")
        data: API parameters

    Returns:
        Parsed JSON response
    """
    session = _get_session()
    encrypted = weapi_encrypt(data)

    r = session.post(
        f"{BASE_URL}{endpoint}",
        data=encrypted,
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def get_song_download_url(song_id, level: str = "lossless") -> Optional[dict]:
    """Get download URL for a song via NetEase weapi.

    Args:
        song_id: Song ID
        level: Quality level (standard, higher, exhigh, lossless, hires, jymaster)

    Returns:
        dict with url, type, size, br, level, or None

    Quality levels and typical formats:
        standard: 128k MP3
        higher: 192k MP3
        exhigh: 320k MP3
        lossless: FLAC (CD quality)
        hires: FLAC (Hi-Res, >44.1kHz)
        jymaster: FLAC (Master quality)
    """
    # NetEase quality level mapping
    level_map = {
        "standard": "standard",
        "higher": "higher",
        "exhigh": "exhigh",
        "lossless": "lossless",
        "hires": "hires",
        "jymaster": "jymaster",
    }
    netease_level = level_map.get(level, "lossless")

    try:
        resp = weapi_request("/weapi/song/enhance/player/url/v1", {
            "ids": f"[{song_id}]",
            "level": netease_level,
            "encodeType": "flac",
        })

        if resp.get("code") == 200 and resp.get("data"):
            dl = resp["data"][0]
            url = dl.get("url")

            if url:
                # Determine file type
                file_type = dl.get("type", "flac")
                if not file_type or file_type == "null":
                    file_type = "flac" if "flac" in str(dl.get("url", "")) else "mp3"

                return {
                    "id": dl.get("id", song_id),
                    "url": url,
                    "type": file_type,
                    "size": dl.get("size", 0),
                    "br": dl.get("br", 0),
                    "level": level,
                    "code": dl.get("code", 200),
                    "gain": dl.get("gain", 0),
                }
            else:
                # No URL available (VIP song without cookie, etc.)
                return None
    except Exception as e:
        pass

    return None


def get_song_detail(song_ids: list) -> dict:
    """Get song details (name, artist, album, fee status, etc.)."""
    resp = weapi_request("/weapi/v3/song/detail", {
        "c": json.dumps([{"id": str(sid)} for sid in song_ids]),
        "ids": json.dumps([int(sid) for sid in song_ids]),
    })
    return resp


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--set-cookie":
        cookie = sys.argv[2] if len(sys.argv) > 2 else input("Paste cookie string: ").strip()
        set_cookie(cookie)
        print("Cookie saved!")
        sys.exit(0)
    
    if len(sys.argv) > 1 and sys.argv[1] == "--clear-cookie":
        clear_cookie()
        print("Cookie cleared!")
        sys.exit(0)

    song_id = sys.argv[1] if len(sys.argv) > 1 else "1357375695"

    print("=== NetEase Weapi Test ===")
    print(f"Cookie: {'SET' if has_cookie() else 'NOT SET (VIP songs will fail)'}")
    if has_cookie():
        preview = NETEASE_COOKIE[:50] + "..." if len(NETEASE_COOKIE) > 50 else NETEASE_COOKIE
        print(f"Cookie preview: {preview}")
    print()

    # Test song detail
    print(f"Song detail for {song_id}:")
    try:
        detail = get_song_detail([song_id])
        if detail.get("code") == 200 and detail.get("songs"):
            song = detail["songs"][0]
            print(f"  Name: {song['name']}")
            print(f"  Artists: {[a['name'] for a in song.get('ar', [])]}")
            print(f"  Album: {(song.get('al') or {}).get('name', '?')}")
            print(f"  Fee: {song.get('fee', '?')}")
    except Exception as e:
        print(f"  Failed: {e}")

    # Test download URL
    print()
    for level in ["lossless", "hires", "exhigh", "higher", "standard"]:
        result = get_song_download_url(song_id, level)
        if result and result.get("url"):
            size_mb = result.get("size", 0) / 1024 / 1024
            print(f"  [{level}] OK - type={result['type']}, {size_mb:.1f}MB, br={result['br']}")
            print(f"         URL: {result['url'][:100]}...")
        else:
            code = result.get('code', '?') if result else 'None'
            print(f"  [{level}] NO URL (code={code})")
    print()
    if not has_cookie():
        print("TIP: Set your NetEase cookie to enable VIP downloads:")
        print("  1. Login to https://music.163.com in your browser")
        print("  2. Press F12 -> Application -> Cookies -> music.163.com")
        print("  3. Copy the MUSIC_U cookie value")
        print('  4. Run: python netease_weapi.py --set-cookie "MUSIC_U=YOUR_VALUE"')
