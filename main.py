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
  python main.py parse "255574"
  python main.py parse --level hires "https://music.163.com/album?id=123"
  python main.py parse --info-only "https://music.163.com/playlist?id=9426599671"
  python main.py decrypt "song.ncm"
  python main.py decrypt "C:/Music/NCM" --output "C:/Music/FLAC"
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ---- Parse subcommand ----
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

    if args.command == "parse":
        cmd_parse(args)
    elif args.command == "decrypt":
        cmd_decrypt(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()