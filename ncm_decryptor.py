#!/usr/bin/env python3
"""NCM (NetEase Cloud Music) file decryptor.

Decrypts .ncm files to their original format (.flac, .mp3, etc.)
Based on the unlock-music project's approach.
"""

import struct
import json
import os
import sys
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad


# Core AES key for decrypting the embedded key box (16 bytes, padded from 15)
_CORE_KEY_15 = bytes.fromhex("687A4852416D736F596B4960415A47")
CORE_KEY = _CORE_KEY_15.ljust(16, b"\x00")

# Meta key for metadata decryption
META_KEY = bytes.fromhex("2331346C6A6B5F215C5D2630553C2728")


def _build_key_box(key_data: bytes) -> bytearray:
    """Build a 256-byte S-box from the decrypted key data for RC4-like decryption."""
    box = bytearray(range(256))
    key_len = len(key_data)
    j = 0
    for i in range(256):
        j = (j + box[i] + key_data[i % key_len]) & 0xFF
        box[i], box[j] = box[j], box[i]
    return box


def _decrypt_audio(audio_data: bytes, key_box: bytearray) -> bytes:
    """Decrypt audio data using the key box (RC4-like stream cipher)."""
    result = bytearray(len(audio_data))
    j = 0
    k = 0
    for i in range(len(audio_data)):
        j = (j + 1) & 0xFF
        k = (k + key_box[j]) & 0xFF
        key_box[j], key_box[k] = key_box[k], key_box[j]
        result[i] = audio_data[i] ^ key_box[(key_box[j] + key_box[k]) & 0xFF]
    return bytes(result)


def decrypt_ncm(input_path: str, output_path: str = None) -> dict:
    """Decrypt a .ncm file and return info dict.

    Args:
        input_path: Path to the .ncm file.
        output_path: Optional output path. Auto-generated if not specified.

    Returns:
        dict with keys: output_path, format, music_name, artist

    Raises:
        ValueError: If the file is not a valid NCM file.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    with open(input_path, "rb") as f:
        # ---- Parse NCM header ----
        magic = f.read(8)
        if magic != b"CTENFDAM":
            raise ValueError(f"Not a valid NCM file (magic: {magic!r})")

        # 2-byte gap
        f.read(2)

        # Read and decrypt the key box
        key_len = struct.unpack("<I", f.read(4))[0]
        key_data_enc = f.read(key_len)
        cipher_core = AES.new(CORE_KEY, AES.MODE_ECB)
        key_data_dec = cipher_core.decrypt(key_data_enc)
        # Remove PKCS7 padding
        key_data_dec = _trim_padding(key_data_dec)

        # Build the key box (S-box)
        key_box = _build_key_box(key_data_dec)

        # Read and decrypt metadata
        meta_len = struct.unpack("<I", f.read(4))[0]
        meta_data_enc = f.read(meta_len)
        meta_data_dec = cipher_core.decrypt(meta_data_enc)
        meta_data_dec = _trim_padding(meta_data_dec)

        # Parse metadata JSON (skip "music:" prefix if present)
        meta_bytes = meta_data_dec
        if meta_bytes.startswith(b"music:"):
            meta_bytes = meta_bytes[6:]
        elif meta_bytes.startswith(b"163 key"):
            # Handle "163 key(Don't modify):" prefix
            idx = meta_bytes.find(b":")
            if idx != -1:
                meta_bytes = meta_bytes[idx + 1 :]

        try:
            meta_json = json.loads(meta_bytes.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            # Try alternate parsing
            meta_json = {
                "musicName": os.path.splitext(os.path.basename(input_path))[0],
                "format": "flac",
            }

        music_name = meta_json.get("musicName", "unknown")
        artist = meta_json.get("artist", [["unknown"]])
        if isinstance(artist, list) and len(artist) > 0:
            if isinstance(artist[0], list):
                artist_str = "/".join(artist[0])
            else:
                artist_str = str(artist[0])
        else:
            artist_str = str(artist)
        audio_format = meta_json.get("format", "flac")

        # Skip CRC (4) + gap (1) + image size (4) = 9 bytes
        crc_data = f.read(4)
        f.read(1)  # gap
        img_size = struct.unpack("<I", f.read(4))[0]

        # Skip album cover image
        f.seek(img_size, 1)

        # Read and decrypt audio data
        audio_data = f.read()
        decrypted_audio = _decrypt_audio(audio_data, key_box)

    # ---- Determine output path ----
    if output_path is None:
        safe_name = _safe_filename(music_name)
        output_dir = os.path.dirname(input_path) or "."
        output_path = os.path.join(output_dir, f"{safe_name}.{audio_format}")

    # Ensure unique filename
    output_path = _unique_path(output_path)

    # Write decrypted file
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


def _trim_padding(data: bytes) -> bytes:
    """Remove PKCS7 padding from data."""
    if not data:
        return data
    pad_len = data[-1]
    if pad_len > 16 or pad_len == 0:
        return data
    if all(b == pad_len for b in data[-pad_len:]):
        return data[:-pad_len]
    return data


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

    ncm_files = [f for f in os.listdir(input_dir) if f.lower().endswith(".ncm")]
    if not ncm_files:
        print(f"No .ncm files found in {input_dir}")
        return

    print(f"Found {len(ncm_files)} .ncm file(s)")
    for filename in ncm_files:
        input_path = os.path.join(input_dir, filename)
        print(f"  Decrypting: {filename} ... ", end="", flush=True)
        try:
            info = decrypt_ncm(input_path, os.path.join(output_dir, ""))
            print(f"OK → {os.path.basename(info['output_path'])} ({info['format']})")
        except Exception as e:
            print(f"FAILED: {e}")


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
        info = decrypt_ncm(target)
        print(f"Decrypted: {info['music_name']} - {info['artist']}")
        print(f"Format:    {info['format']}")
        print(f"Output:    {info['output_path']}")
        print(f"Size:      {info['size']:,} bytes")
    else:
        print(f"Error: '{target}' is not a valid file or directory")
        sys.exit(1)
