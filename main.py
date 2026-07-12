#!/usr/bin/env python3
"""NetEase Cloud Music Toolkit - Unified CLI.

Two tools in one:
  1. Parser  - Parse NetEase links and download songs in high quality
  2. Decrypt - Decrypt .ncm files to .flac/.mp3

Usage:
  python main.py parse "https://music.163.com/playlist?id=9426599671"
  python main.py parse "SONG_ID" --level hires
  python main.py decrypt "song.ncm"
  python main.py decrypt "C:/Music/NCM" --output "C:/Music/FLAC"
"""

import os
import sys
import argparse


def cmd_source(args):
    """Handle the source subcommand."""
    from music_sources import (list_sources, toggle_source, set_preferred_source,
                                add_custom_url, remove_custom_url, get_all_sources,
                                get_source_config)

    action = args.action or "list"
    value = args.value

    if action == "list":
        list_sources()
    elif action == "toggle":
        if not value:
            print("Usage: python main.py source toggle <source_id>")
            print("Available IDs:", ", ".join(s["id"] for s in get_all_sources()))
            return
        new_state = toggle_source(value)
        print(f"Source [{value}]: {'[ON]' if new_state else '[OFF]'}")
    elif action == "prefer":
        if not value:
            print("Usage: python main.py source prefer <source_id>")
            print("Available IDs:", ", ".join(s["id"] for s in get_all_sources()))
            return
        set_preferred_source(value)
        print(f"Preferred source set to: {value}")
    elif action == "add-url":
        if not value:
            print("Usage: python main.py source add-url <url>")
            return
        add_custom_url(value)
        print(f"Added custom URL: {value}")
        print("Run 'python main.py sources' to verify")
    elif action == "remove-url":
        if not value:
            cfg = get_source_config()
            urls = cfg.get("custom_urls", [])
            if urls:
                print("Custom URLs:")
                for u in urls:
                    print(f"  {u}")
            else:
                print("No custom URLs configured.")
            return
        remove_custom_url(value)
        print(f"Removed: {value}")

def cmd_cookie(args):
    """Handle the 'cookie' subcommand."""
    from netease_weapi import set_cookie, clear_cookie, has_cookie, NETEASE_COOKIE

    action = args.action or "status"

    if action == "set":
        value = args.value
        if not value:
            value = input("Paste your NetEase cookie string: ").strip()
        if value:
            set_cookie(value)
            print("Cookie saved successfully!")
            print()
            print("How to get your cookie:")
            print("  1. Login to https://music.163.com in your browser")
            print("  2. Press F12 -> Application -> Cookies -> music.163.com")
            print("  3. Find MUSIC_U and copy its value")
            print('  4. Run: python main.py cookie set "MUSIC_U=YOUR_COOKIE_VALUE"')
        else:
            print("No cookie provided.")
    elif action == "clear":
        clear_cookie()
        print("Cookie cleared.")
    else:
        print("Cookie status:")
        if has_cookie():
            from netease_weapi import is_vip
            preview = NETEASE_COOKIE[:60] + "..." if len(NETEASE_COOKIE) > 60 else NETEASE_COOKIE
            print(f"  Cookie: SET")
            print(f"  Preview: {preview}")
            print("  Checking VIP...", end=" ", flush=True)
            vip = is_vip()
            if vip is True:
                print("YES - FLAC available")
            elif vip is False:
                print("NO - only M4A")
            else:
                print("cannot determine")
        else:
            print(f"  Status: NOT SET")
            print()
            print("  VIP songs will only download in M4A quality without a cookie.")
            print("  Set your cookie to enable FLAC downloads for VIP songs:")
            print("    1. Login to https://music.163.com")
            print("    2. F12 -> Application -> Cookies -> music.163.com")
            print("    3. Copy the MUSIC_U cookie value")
            print('    4. Run: python main.py cookie set "MUSIC_U=YOUR_VALUE"')

def cmd_sources(args):
    """Handle the 'sources' subcommand."""
    from music_sources import check_source_health, get_enabled_sources, fetch_source_configs

    print("=== Music Source Health Check ===")
    print()

    # Check source URLs
    health = check_source_health()
    for url, status in health.items():
        icon = "OK" if status["ok"] else "FAIL"
        print(f"  [{icon}] {url}")
        if status["ok"]:
            print(f"           Sources: {status['sources_count']}")
        else:
            print(f"           Error: {status['error']}")
    print()

    # Show enabled sources
    sources = get_enabled_sources()
    if sources:
        print(f"Enabled sources ({len(sources)}):")
        for s in sources:
            levels = ", ".join(s.get("levels", []))
            print(f"  [{s['id']}] {s['name']} - levels: {levels}")
    else:
        print("No enabled sources found!")
    print()

    # Current active config URL
    config = fetch_source_configs()
    if config.get("source_url"):
        print(f"Active config: {config['source_url']}")

def cmd_parse(args):
    """Handle the 'parse' subcommand."""
    from netease_parser import (
        _parse_link, get_playlist, get_album, get_song_url,
        download_playlist, download_album, download_song,
    )

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
            else:
                filepath = download_song(song_id, args.output,
                                         level=args.level, raw_input=args.link)
                print(f"\nSaved to: {filepath}")

    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


def cmd_decrypt(args):
    """Handle the 'decrypt' subcommand."""
    from ncm_decryptor import decrypt_ncm, batch_decrypt

    target = args.input
    out_dir = args.output

    if os.path.isdir(target):
        batch_decrypt(target, out_dir)
    elif os.path.isfile(target):
        info = decrypt_ncm(target)
        print(f"Music:  {info['music_name']} - {info['artist']}")
        print(f"Format: {info['format']}")
        print(f"Output: {info['output_path']}")
        print(f"Size:   {info['size']:,} bytes")
    else:
        print(f"Error: '{target}' is not a valid file or directory")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="NetEase Cloud Music Toolkit - Parse links and Decrypt NCM files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py parse "https://music.163.com/playlist?id=9426599671"
  python main.py cookie status                     Check cookie status
  python main.py cookie set "MUSIC_U=xxx"          Set cookie for VIP FLAC
  python main.py cookie clear                       Clear saved cookie
  python main.py sources                            Check music source health
  python main.py parse "255574"
  python main.py parse --level hires "https://music.163.com/album?id=123"
  python main.py parse --info-only "https://music.163.com/playlist?id=9426599671"
  python main.py decrypt "song.ncm"
  python main.py decrypt "C:/Music/NCM" --output "C:/Music/FLAC"
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ---- Parse subcommand ----
    # ---- Sources subcommand ----
    sources_parser = subparsers.add_parser("sources", help="Check music source availability")
    sources_parser.add_argument("--check", action="store_true", default=True,
                                help="Check source availability")

    # ---- Cookie subcommand ----
    cookie_parser = subparsers.add_parser("cookie", help="Manage NetEase login cookie for VIP FLAC")
    cookie_parser.add_argument("action", nargs="?", choices=["set", "clear", "status"],
                               default="status",
                               help="set/clear/check cookie status")
    cookie_parser.add_argument("value", nargs="?", help="Cookie string (for set action)")

    # ---- Source subcommand ----
    src_parser = subparsers.add_parser("source", help="Manage music sources (list/toggle/prefer/add-url)")
    src_parser.add_argument("action", nargs="?", choices=["list", "toggle", "prefer", "add-url", "remove-url"],
                            default="list", help="Action to perform")
    src_parser.add_argument("value", nargs="?", help="Source ID or URL (for toggle/prefer/add-url)")

    parse_parser = subparsers.add_parser("parse", help="Parse NetEase link and download songs")
    parse_parser.add_argument("link", help="NetEase Cloud Music link or numeric ID")
    parse_parser.add_argument("-o", "--output", default="downloads",
                              help="Output directory (default: downloads)")
    parse_parser.add_argument("-l", "--level", default="lossless",
                              choices=["lossless", "hires", "exhigh", "higher", "standard"],
                              help="Audio quality level (default: lossless)")
    parse_parser.add_argument("--info-only", action="store_true",
                              help="Only show track info, don't download")

    # ---- Decrypt subcommand ----
    decrypt_parser = subparsers.add_parser("decrypt", help="Decrypt .ncm files to .flac/.mp3")
    decrypt_parser.add_argument("input", help="Input .ncm file or directory containing .ncm files")
    decrypt_parser.add_argument("-o", "--output", default=None,
                                help="Output directory (default: same as input)")

    args = parser.parse_args()

    if args.command == "sources":
        cmd_sources(args)
    elif args.command == "cookie":
        cmd_cookie(args)
    elif args.command == "source":
        cmd_source(args)
    elif args.command == "parse":
        cmd_parse(args)
    elif args.command == "decrypt":
        cmd_decrypt(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()