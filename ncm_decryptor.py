#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NCM (NetEase Cloud Music) file decryptor.

Decrypts .ncm files to their original format (.flac, .mp3, etc.)
Based on the ncmdump project approach.
"""

import base64
import json
import os
import struct
import sys

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad


CORE_KEY = bytes.fromhex("687A4852416D736F356B496E62617857")
META_KEY = bytes.fromhex("2331346C6A6B5F215C5D2630553C2728")


def _build_key_box(key_data: bytes) -> bytearray:
    """Build a 256-byte S-box from the decrypted key data."""
    box = bytearray(range(256))
    key_len = len(key_data)
    j = 0
    for i in range(256):
        j = (j + box[i] + key_data[i % key_len]) & 0xFF
        box[i], box[j] = box[j], box[i]
    return box


def _decrypt_audio(audio_data: bytes, sbox: bytearray) -> bytes:
    """Decrypt audio using a static RC4-like key stream."""
    # Generate static key stream from S-box (not self-modifying)
    stream = bytearray()
    for i in range(256):
        stream.append(sbox[(sbox[i] + sbox[(i + sbox[i]) & 0xFF]) & 0xFF])

    # Repeat stream to cover all audio data, skip first byte
    full_stream = (stream * (len(audio_data) // 256 + 1))[1 : 1 + len(audio_data)]
    return bytes(a ^ s for a, s in zip(audio_data, full_stream))


def _parse_artist(artist_field) -> str:
    """Parse the artist field from NCM metadata into a string."""
    if isinstance(artist_field, str):
        return artist_field
    if isinstance(artist_field, list) and len(artist_field) > 0:
        names = []
        for item in artist_field:
            if isinstance(item, list) and len(item) > 0:
                names.append(str(item[0]))
            elif isinstance(item, str):
                names.append(item)
        return "/".join(names) if names else "unknown"
    return "unknown"


def decrypt_ncm(input_path: str, output_path: str = None) -> dict:
    """Decrypt a .ncm file.

    Args:
        input_path: Path to the .ncm file.
        output_path: Optional output path. Auto-generated if not specified.

    Returns:
        dict with keys: output_path, format, music_name, artist
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    with open(input_path, "rb") as f:
        # ---- Verify magic ----
        header = f.read(8)
        if header != b"CTENFDAM":
            raise ValueError(f"Not a valid NCM file (magic: {header!r})")

        # 2-byte gap
        f.seek(2, 1)

        # ---- Read and decrypt key box ----
        key_len = struct.unpack("<I", f.read(4))[0]
        key_data = bytearray(f.read(key_len))
        # XOR each byte with 0x64 before AES decryption
        key_data = bytes(b ^ 0x64 for b in key_data)

        cipher_core = AES.new(CORE_KEY, AES.MODE_ECB)
        key_data = unpad(cipher_core.decrypt(key_data), 16)
        # Skip first 17 bytes (identifier/metadata prefix)
        key_data = key_data[17:]

        # Build the S-box
        sbox = _build_key_box(key_data)

        # ---- Read and decrypt metadata ----
        meta_len = struct.unpack("<I", f.read(4))[0]

        if meta_len:
            meta_data = bytearray(f.read(meta_len))
            # XOR each byte with 0x63
            meta_data = bytes(b ^ 0x63 for b in meta_data)

            # First 22 bytes are identifier, rest is base64-encoded AES-encrypted JSON
            meta_b64 = meta_data[22:]
            meta_enc = base64.b64decode(meta_b64)

            cipher_meta = AES.new(META_KEY, AES.MODE_ECB)
            meta_plain = unpad(cipher_meta.decrypt(meta_enc), 16).decode("utf-8")

            # Strip BOM and "music:" prefix
            if meta_plain.startswith("\ufeff"):
                meta_plain = meta_plain[1:]
            if meta_plain.startswith("music:"):
                meta_plain = meta_plain[6:]

            meta_json = json.loads(meta_plain)
            music_name = meta_json.get("musicName", "unknown")
            artist_str = _parse_artist(meta_json.get("artist"))
            audio_format = meta_json.get("format", "flac")
        else:
            music_name = os.path.splitext(os.path.basename(input_path))[0]
            artist_str = "unknown"
            file_size = os.path.getsize(input_path)
            audio_format = "flac" if file_size > 16 * 1024 * 1024 else "mp3"

        # ---- Skip CRC/gap, read album cover ----
        f.seek(5, 1)  # crc(4) + gap(1)
        image_space = struct.unpack("<I", f.read(4))[0]
        image_size = struct.unpack("<I", f.read(4))[0]
        f.seek(image_size, 1)  # skip image data
        f.seek(image_space - image_size, 1)  # skip remaining image space

        # ---- Read and decrypt audio ----
        audio_data = f.read()
        decrypted_audio = _decrypt_audio(audio_data, sbox)

    # ---- Write output ----
    if output_path is None:
        safe_name = _safe_filename(music_name)
        output_dir = os.path.dirname(input_path) or "."
        output_path = os.path.join(output_dir, f"{safe_name}.{audio_format}")

    output_path = _unique_path(output_path)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with open(output_path, "wb") as f:
        f.write(decrypted_audio)

    return {
        "output_path": output_path,
        "format": audio_format,
        "music_name": music_name,
        "artist": artist_str,
        "size": len(decrypted_audio),
    }


def _safe_filename(name: str) -> str:
    """Convert a name to a filesystem-safe filename."""
    unsafe_chars = r'<>:"/\|?*'
    for ch in unsafe_chars:
        name = name.replace(ch, "_")
    return name.strip().strip(".") or "unknown"


def _unique_path(path: str) -> str:
    """Ensure the path is unique by appending a counter if needed."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    counter = 1
    while os.path.exists(f"{base} ({counter}){ext}"):
        counter += 1
    return f"{base} ({counter}){ext}"


def batch_decrypt(input_dir: str, output_dir: str = None):
    """Decrypt all .ncm files in a directory."""
    if output_dir is None:
        output_dir = input_dir

    ncm_files = sorted(f for f in os.listdir(input_dir) if f.lower().endswith(".ncm"))
    if not ncm_files:
        print(f"No .ncm files found in {input_dir}")
        return

    print(f"Found {len(ncm_files)} .ncm file(s)")
    success = 0
    for filename in ncm_files:
        input_path = os.path.join(input_dir, filename)
        print(f"  {filename} ... ", end="", flush=True)
        try:
            info = decrypt_ncm(input_path, os.path.join(output_dir, ""))
            print(f"OK -> {os.path.basename(info['output_path'])} ({info['format']}, {info['size']/1024/1024:.1f}MB)")
            success += 1
        except Exception as e:
            print(f"FAILED: {e}")
    print(f"\nDone: {success}/{len(ncm_files)} decrypted")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python ncm_decryptor.py <file.ncm|directory> [output_dir]")
        print("  Decrypt .ncm files to .flac/.mp3")
        sys.exit(1)

    target = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else None

    if os.path.isdir(target):
        batch_decrypt(target, out_dir)
    elif os.path.isfile(target):
        info = decrypt_ncm(target, out_dir)
        print(f"Music:  {info['music_name']} - {info['artist']}")
        print(f"Format: {info['format']}")
        print(f"Output: {info['output_path']}")
        print(f"Size:   {info['size']:,} bytes ({info['size']/1024/1024:.1f}MB)")
    else:
        print(f"Error: '{target}' is not a valid file or directory")
        sys.exit(1)