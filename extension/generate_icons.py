"""
Generate placeholder extension icons (solid indigo squares).
Run once: python generate_icons.py
"""
import os
import struct
import zlib


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    chunk = tag + data
    return struct.pack(">I", len(data)) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)


def create_solid_png(size: int, r: int, g: int, b: int) -> bytes:
    """Create a minimal single-color RGB PNG without dependencies."""
    # IHDR: width, height, bit_depth=8, color_type=2 (RGB), compress=0, filter=0, interlace=0
    ihdr_data = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)

    # Raw image data: one filter byte (0) per scanline, then RGB pixels
    raw = b""
    row = b"\x00" + bytes([r, g, b]) * size
    raw = row * size

    idat_data = zlib.compress(raw, level=9)

    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr_data)
        + _png_chunk(b"IDAT", idat_data)
        + _png_chunk(b"IEND", b"")
    )


if __name__ == "__main__":
    # Indigo #4f46e5 — matches the extension's accent color
    R, G, B = 0x4F, 0x46, 0xE5

    icons_dir = os.path.join(os.path.dirname(__file__), "icons")
    os.makedirs(icons_dir, exist_ok=True)

    for size in (16, 48, 128):
        path = os.path.join(icons_dir, f"icon{size}.png")
        with open(path, "wb") as f:
            f.write(create_solid_png(size, R, G, B))
        print(f"  Created {path} ({size}x{size})")

    print("Icons generated.")
