# -*- coding: utf-8 -*-
"""Multi-source music API manager with auto-fallback.

Fetches music source configurations from multiple URLs and provides
unified search/download with automatic fallback between sources.
"""

import json
import os
import re
import time
import requests
from typing import Optional

# ============================================================
# Source config URLs - checked in order, first available wins
# ============================================================
SOURCE_URLS = [
    "https://musicapi.haitangw.net/music.json",
    "https://13413.kstore.vip/QingMusic/music.json",
]

# Cache source configs
_source_cache: dict = {"sources": [], "fetched_at": 0, "source_url": ""}
_CACHE_TTL = 3600  # 1 hour

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

# ============================================================
# Source preferences (user-customizable)
# ============================================================
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(HERE, "source_config.json")

_default_config = {
    "preferred": "wy",
    "disabled": [],
    "custom_urls": [],
}


def _load_config() -> dict:
    """Load source preferences from config file."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                for k, v in _default_config.items():
                    if k not in cfg:
                        cfg[k] = v
                return cfg
    except Exception:
        pass
    return dict(_default_config)


def _save_config(cfg: dict):
    """Save source preferences to config file."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_source_config() -> dict:
    """Get current source configuration. Returns dict with preferred, disabled, custom_urls."""
    return _load_config()


def set_preferred_source(source_id: str):
    """Set the preferred music source platform (wy/kg/kw/tx/mg)."""
    cfg = _load_config()
    cfg["preferred"] = source_id
    _save_config(cfg)


def toggle_source(source_id: str) -> bool:
    """Toggle a source on/off. Returns True if enabled after toggle."""
    cfg = _load_config()
    disabled = cfg.get("disabled", [])
    if source_id in disabled:
        disabled.remove(source_id)
        _save_config(cfg)
        return True
    else:
        disabled.append(source_id)
        _save_config(cfg)
        return False


def add_custom_url(url: str):
    """Add a custom source config URL to the fetch list."""
    cfg = _load_config()
    custom = cfg.get("custom_urls", [])
    if url not in custom:
        custom.append(url)
        _save_config(cfg)


def remove_custom_url(url: str):
    """Remove a custom source config URL."""
    cfg = _load_config()
    custom = cfg.get("custom_urls", [])
    if url in custom:
        custom.remove(url)
        _save_config(cfg)


def get_all_urls() -> list:
    """Get all source config URLs (built-in + user custom)."""
    cfg = _load_config()
    return SOURCE_URLS + cfg.get("custom_urls", [])


def get_all_sources() -> list:
    """Get all sources with status info. Returns list of dicts."""
    cfg = _load_config()
    config = fetch_source_configs()
    preferred = cfg.get("preferred", "wy")
    disabled = cfg.get("disabled", [])

    result = []
    for s in config.get("sources", []):
        sid = s.get("id", "?")
        result.append({
            "id": sid,
            "name": s.get("name", sid),
            "enabled": sid not in disabled and s.get("enabled", True),
            "levels": s.get("levels", []),
            "is_preferred": sid == preferred,
        })
    return result


def list_sources():
    """Print a formatted table of all sources and their status."""
    cfg = _load_config()
    preferred = cfg.get("preferred", "wy")

    sources = get_all_sources()
    print(f"\n=== Music Sources ({len(sources)} total) ===")
    print(f"{'Status':<8} {'Pref':<6} {'ID':<6} {'Name':<10} {'Levels'}")
    print("-" * 60)
    for s in sources:
        status = "[ON] " if s["enabled"] else "[OFF]"
        pref = "*" if s["is_preferred"] else " "
        levels = ", ".join(s["levels"])
        print(f"{status:<8} {pref:<6} [{s['id']:<4}] {s['name']:<10} {levels}")

    custom = cfg.get("custom_urls", [])
    if custom:
        print(f"\nCustom source URLs ({len(custom)}):")
        for u in custom:
            print(f"  {u}")
    print(f"Config file: {CONFIG_FILE}")


def fetch_source_configs(force: bool = False) -> dict:
    """Fetch music source configurations from all URLs.

    Tries each URL in order until one succeeds. Results are cached.

    Returns:
        dict with keys: sources (list of source dicts),
                        source_url (which URL was used),
                        fetched_at (timestamp)
    """
    now = int(time.time())
    if not force and _source_cache["sources"] and (now - _source_cache["fetched_at"]) < _CACHE_TTL:
        return _source_cache

    all_urls = get_all_urls()
    for url in all_urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            data = r.json()
            sources = data.get("lines", data) if isinstance(data, dict) else data
            if isinstance(sources, list) and len(sources) > 0:
                _source_cache["sources"] = sources
                _source_cache["source_url"] = url
                _source_cache["fetched_at"] = now
                return _source_cache
        except Exception:
            continue

    return _source_cache  # Return whatever we have (possibly empty)


def get_enabled_sources() -> list:
    """Get list of user-enabled music sources, respecting preferences.

    Returns:
        List of source dicts with id, name, enabled, levels
    """
    cfg = _load_config()
    config = fetch_source_configs()
    disabled = cfg.get("disabled", [])
    return [
        s for s in config.get("sources", [])
        if s.get("enabled", True) and s.get("id") not in disabled
    ]


def check_source_health() -> dict:
    """Check which source URLs are reachable.

    Returns:
        dict mapping URL to health status: {url: {ok: bool, sources_count: int, error: str}}
    """
    results = {}
    all_urls = get_all_urls()
    for url in all_urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            r.raise_for_status()
            data = r.json()
            sources = data.get("lines", data) if isinstance(data, dict) else data
            count = len(sources) if isinstance(sources, list) else 0
            results[url] = {"ok": True, "sources_count": count, "error": None}
        except Exception as e:
            results[url] = {"ok": False, "sources_count": 0, "error": str(e)}
    return results


def download_via_yuafeng(song_name: str, artist: str = "",
                         output_dir: str = "downloads",
                         source: str = "wy",
                         level: str = "lossless") -> Optional[str]:
    """Download a song via yuafeng.cn API as fallback."""
    try:
        from yuafeng_api import download_song_by_name
        return download_song_by_name(song_name, artist, output_dir, source)
    except ImportError:
        return None
    except Exception:
        return None


def download_with_fallback(song_name: str, artist: str = "",
                           output_dir: str = "downloads",
                           preferred_source: str = "",
                           level: str = "lossless") -> Optional[str]:
    """Download a song with multi-source fallback, respecting user preferences.

    Tries preferred_source first, then falls back to other enabled sources.

    Args:
        song_name: Song name
        artist: Artist name
        output_dir: Output directory
        preferred_source: Preferred platform (empty = use config default)
        level: Quality level hint (lossless, hires, exhigh, higher, standard)

    Returns:
        File path if successful, None if all sources fail
    """
    if not preferred_source:
        cfg = _load_config()
        preferred_source = cfg.get("preferred", "wy")

    # Get enabled sources from config
    enabled = get_enabled_sources()
    source_ids = [s["id"] for s in enabled]

    # Try preferred source first
    try_order = [preferred_source] if preferred_source in source_ids else []
    for sid in source_ids:
        if sid not in try_order:
            try_order.append(sid)

    last_error = None
    for sid in try_order:
        try:
            result = download_via_yuafeng(song_name, artist, output_dir, sid, level)
            if result:
                return result
        except Exception as e:
            last_error = str(e)
            continue

    if last_error:
        raise RuntimeError(f"All sources failed for '{artist} - {song_name}'. Last error: {last_error}")
    return None


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "list":
            list_sources()
            sys.exit(0)
        elif cmd == "toggle" and len(sys.argv) > 2:
            sid = sys.argv[2]
            new_state = toggle_source(sid)
            print(f"Source [{sid}]: {'ON' if new_state else 'OFF'}")
            sys.exit(0)
        elif cmd == "prefer" and len(sys.argv) > 2:
            set_preferred_source(sys.argv[2])
            print(f"Preferred source: {sys.argv[2]}")
            sys.exit(0)
        elif cmd == "add-url" and len(sys.argv) > 2:
            add_custom_url(sys.argv[2])
            print(f"Added: {sys.argv[2]}")
            sys.exit(0)
        elif cmd == "config":
            cfg = get_source_config()
            print(json.dumps(cfg, ensure_ascii=False, indent=2))
            sys.exit(0)

    # Default: health check + source list
    print("=== Music Sources Health Check ===")
    health = check_source_health()
    for url, status in health.items():
        icon = "OK" if status["ok"] else "FAIL"
        print(f"  [{icon}] {url}")
        if status["ok"]:
            print(f"         Sources: {status['sources_count']}")
        else:
            print(f"         Error: {status['error']}")

    list_sources()
