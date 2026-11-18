#!/usr/bin/env python3
"""
REA Binary Patcher: 90° Clockwise Touchscreen Rotation for Rectangular 2.4" (320x240) CYD Display.

Applies two coordinated binary patches to the reverse-engineered Bruce CYD-2432S028 image:
1. Segment 1 (.dram0.data, vaddr 0x3FFBDFD0 = `CYD28_TouchR touch` instance):
   - Swaps `touch.sizeX_px` (+0x20: 320 -> 240) and `touch.sizeY_px` (+0x24: 240 -> 320)
     so that after the 90° CW SwapXY transform, the horizontal axis spans the full
     [0..320] width and the vertical axis spans the full [0..240] height of the
     rectangular 2.4" display (avoiding 240px X-clipping and 320px Y-overflow).
2. Segment 2 (.flash.text, vaddr 0x401385C0 = `touchCfg()`):
   - Rotates the per-rotation touch orientation table by 90° clockwise:
       (u_new, v_new) = (1 - v_orig, u_orig)
     Mapping for rotations r = 0, 1, 2, 3:
       SwapXY[0..3]  = {0, 1, 0, 1}  (was {1, 0, 1, 0})
       MirrorX[0..3] = {1, 1, 0, 0}  (was {1, 0, 0, 1})
       MirrorY[0..3] = {1, 0, 0, 1}  (was {0, 0, 1, 1})
3. Recomputes the ESP-IDF XOR segment checksum and appended SHA-256 image digest.
"""

import hashlib
import shutil
import struct
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ORIG_BIN = REPO_ROOT / "firmware" / "Bruce-CYD-2432S028-orig.bin"
CURRENT_BIN = REPO_ROOT / "firmware" / "Bruce-CYD-2432S028.bin"
CLONED_BIN = REPO_ROOT / "firmware" / "Bruce-CYD-2432S024R-90CW.bin"
FACTORY_90CW_BIN = REPO_ROOT / "rea_analysis" / "partitions" / "factory-90cw.bin"

FACTORY_OFFSET = 0x10000


def parse_esp_image(factory_bytes: bytes):
    header = factory_bytes[:24]
    magic, seg_count = header[0], header[1]
    assert magic == 0xE9, f"Invalid ESP image magic: 0x{magic:02X}"
    pos = 24
    segments = []
    for i in range(seg_count):
        load_addr, data_len = struct.unpack("<II", factory_bytes[pos : pos + 8])
        seg_data = bytearray(factory_bytes[pos + 8 : pos + 8 + data_len])
        segments.append({"index": i, "load_addr": load_addr, "data": seg_data})
        pos += 8 + data_len
    return header, segments, pos


def build_esp_image(header: bytes, segments: list) -> bytes:
    out = bytearray(header)
    xor_chk = 0xEF
    for seg in segments:
        data = seg["data"]
        out.extend(struct.pack("<II", seg["load_addr"], len(data)))
        out.extend(data)
        for b in data:
            xor_chk ^= b

    # Pad to 16-byte alignment where final byte is the XOR checksum
    while (len(out) + 1) % 16 != 0:
        out.append(0x00)
    out.append(xor_chk)

    # If hash_appended byte (offset 23) is 1, append SHA-256 digest
    if header[23] == 1:
        digest = hashlib.sha256(out).digest()
        out.extend(digest)
    return bytes(out)


def patch_firmware():
    if not ORIG_BIN.exists():
        shutil.copy2(CURRENT_BIN, ORIG_BIN)
        print(f"[+] Backed up original 2.8\" binary to {ORIG_BIN.name}")

    flash_orig = bytearray(ORIG_BIN.read_bytes())
    factory_orig = bytes(flash_orig[FACTORY_OFFSET:])
    header, segments, end_pos = parse_esp_image(factory_orig)

    # 1. Patch Segment 1 (.dram0.data): CYD28_TouchR touch at 0x3FFBDFD0
    seg1 = segments[1]
    assert seg1["load_addr"] == 0x3FFBDB60
    touch_off = 0x3FFBDFD0 - seg1["load_addr"]  # 0x470
    old_size_x, old_size_y = struct.unpack("<ii", seg1["data"][touch_off + 0x20 : touch_off + 0x28])
    print(f"[*] Segment 1 (`touch` @ 0x3FFBDFD0): old sizeX_px={old_size_x}, sizeY_px={old_size_y}")
    assert (old_size_x, old_size_y) == (320, 240), f"Unexpected touch size: {old_size_x}x{old_size_y}"

    # Set sizeX_px = 240, sizeY_px = 320 for 90° CW rectangular 320x240 display
    seg1["data"][touch_off + 0x20 : touch_off + 0x28] = struct.pack("<ii", 240, 320)
    new_size_x, new_size_y = struct.unpack("<ii", seg1["data"][touch_off + 0x20 : touch_off + 0x28])
    print(f"[+] Segment 1 (`touch` @ 0x3FFBDFD0): new sizeX_px={new_size_x}, sizeY_px={new_size_y}")

    # 2. Patch Segment 2 (.flash.text): touchCfg() at 0x401385C0
    seg2 = segments[2]
    assert seg2["load_addr"] == 0x400D0020
    patch_va = 0x401385D4
    patch_off = patch_va - seg2["load_addr"]

    expected_orig_code = bytes.fromhex(
        "82410c"  # s8i a8, a1, 12  (SwapXY[0] = 1)
        "92410d"  # s8i a9, a1, 13  (SwapXY[1] = 0)
        "82410e"  # s8i a8, a1, 14  (SwapXY[2] = 1)
        "92410f"  # s8i a9, a1, 15  (SwapXY[3] = 0)
        "824108"  # s8i a8, a1, 8   (MirrorX[0] = 1)
        "82410b"  # s8i a8, a1, 11  (MirrorX[3] = 1)
        "824106"  # s8i a8, a1, 6   (MirrorY[2] = 1)
        "824107"  # s8i a8, a1, 7   (MirrorY[3] = 1)
        "8831"    # l32i.n a8, a1, 12
        "924109"  # s8i a9, a1, 9   (MirrorX[1] = 0)
        "92410a"  # s8i a9, a1, 10  (MirrorX[2] = 0)
        "8932"    # s32i.n a8, a2, 12
        "8821"    # l32i.n a8, a1, 8
        "924104"  # s8i a9, a1, 4   (MirrorY[0] = 0)
        "924105"  # s8i a9, a1, 5   (MirrorY[1] = 0)
    )
    actual_orig_code = bytes(seg2["data"][patch_off : patch_off + len(expected_orig_code)])
    assert actual_orig_code == expected_orig_code, (
        f"Unexpected instructions at 0x{patch_va:08X}: {actual_orig_code.hex()}"
    )

    patched_90cw_code = bytes.fromhex(
        "92410c"  # s8i a9, a1, 12  (SwapXY[0] = 0)
        "82410d"  # s8i a8, a1, 13  (SwapXY[1] = 1)
        "92410e"  # s8i a9, a1, 14  (SwapXY[2] = 0)
        "82410f"  # s8i a8, a1, 15  (SwapXY[3] = 1)
        "824108"  # s8i a8, a1, 8   (MirrorX[0] = 1)
        "824109"  # s8i a8, a1, 9   (MirrorX[1] = 1)
        "824104"  # s8i a8, a1, 4   (MirrorY[0] = 1)
        "824107"  # s8i a8, a1, 7   (MirrorY[3] = 1)
        "8831"    # l32i.n a8, a1, 12
        "92410a"  # s8i a9, a1, 10  (MirrorX[2] = 0)
        "92410b"  # s8i a9, a1, 11  (MirrorX[3] = 0)
        "8932"    # s32i.n a8, a2, 12
        "8821"    # l32i.n a8, a1, 8
        "924105"  # s8i a9, a1, 5   (MirrorY[1] = 0)
        "924106"  # s8i a9, a1, 6   (MirrorY[2] = 0)
    )
    assert len(patched_90cw_code) == len(expected_orig_code)
    seg2["data"][patch_off : patch_off + len(patched_90cw_code)] = patched_90cw_code
    print(f"[+] Segment 2 (`touchCfg` @ 0x401385C0): patched 42 bytes at 0x{patch_va:08X}")

    # Rebuild factory.bin with valid XOR checksum and appended SHA-256
    new_factory = build_esp_image(header, segments)
    FACTORY_90CW_BIN.write_bytes(new_factory)
    print(f"[+] Wrote {FACTORY_90CW_BIN.name} ({len(new_factory)} bytes, SHA256={hashlib.sha256(new_factory).hexdigest()})")

    # Embed into full flash image
    new_flash = bytearray(flash_orig)
    new_flash[FACTORY_OFFSET : FACTORY_OFFSET + len(new_factory)] = new_factory
    new_flash_bytes = bytes(new_flash)

    CLONED_BIN.write_bytes(new_flash_bytes)
    CURRENT_BIN.write_bytes(new_flash_bytes)
    flash_sha = hashlib.sha256(new_flash_bytes).hexdigest()
    print(f"[+] Wrote {CLONED_BIN.name} and updated {CURRENT_BIN.name} (SHA256={flash_sha})")


if __name__ == "__main__":
    patch_firmware()
