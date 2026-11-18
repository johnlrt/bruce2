#!/usr/bin/env python3
"""
REA Reverse-Engineering & Bit-Exact Firmware Reconstruction Pipeline
for Bruce CYD-2432S028 (ESP32-2432S028R / Cheap Yellow Display).

Uses https://github.com/morluto/rea (`rea-agents`) to:
  1. Inspect & extract ESP32 flash image regions (`bootloader`, `partition-table`, `nvs`, `factory`, `spiffs`).
  2. Inspect & extract the 6 Xtensa segments from `partitions/factory.bin`.
  3. Reconstruct an Xtensa ELF32 image (`EM_XTENSA = 94`) for `rea inspect-with-objdump` & `rea inspect-binary-hardening`.
  4. Recover the 4 embedded gzipped WebUI assets (`index.js`, `index.css`, `index.html`, `login.html`) from DROM (`segment-00.bin`) and generate `include/webFiles.h`.
  5. Rebuild `factory.bin` and the complete `Bruce-CYD-2432S028.bin` flash image from the extracted segments, verifying ESP-IDF XOR checksums, SHA-256 digests, and bit-exact image parity.
"""

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path


SEGMENTS_SPEC = [
    ("segment-00.bin", 0x3F400020, 4, ".flash.rodata", "mapped"),
    ("segment-01.bin", 0x3FFBDB60, 6, ".dram0.data",   "loaded"),
    ("segment-02.bin", 0x400D0020, 5, ".flash.text",   "mapped"),
    ("segment-03.bin", 0x3FFC2CAC, 6, ".dram0.data2",  "loaded"),
    ("segment-04.bin", 0x40080000, 5, ".iram0.text",   "loaded"),
    ("segment-05.bin", 0x50000200, 6, ".rtc.data",     "loaded"),
]

WEBUI_GZIP_MAP = [
    ("index_js",   "index.js",   0xA80C, 8434),
    ("index_css",  "index.css",  0xC8FE, 2421),
    ("index_html", "index.html", 0xD274, 4687),
    ("login_html", "login.html", 0xE4C3, 601),
]

ENTRY_ADDR = 0x40083050
EXPECTED_FLASH_SHA256 = "f127d4bbe4a4c1954c9dad975365bf6fa0ed8cab82471b641b0af0b4c1b9b587"
EXPECTED_FACTORY_APP_SHA256 = "a83a07b54aa96b5591a94de60887114ab050ce4c44e2fc63a3fc3697d256467d"


def compute_esp_checksum(segments_bytes: list[bytes]) -> int:
    """Compute ESP-IDF XOR checksum seeded with 0xEF over all segment payloads."""
    chk = 0xEF
    for seg in segments_bytes:
        for b in seg:
            chk ^= b
    return chk


def build_esp_app_image(segments: list[tuple[int, bytes]], entry_addr: int = ENTRY_ADDR) -> bytes:
    """
    Construct a valid ESP32 application image (`esp_image_header_t` + segments +
    16-byte aligned XOR checksum + appended SHA-256 digest).
    """
    # 24-byte esp_image_header_t:
    # magic=0xE9, segment_count=len(segments), spi_mode=2 (DIO), spi_speed_size=0x20 (40MHz, 4MB),
    # entry_addr, wp_pin=0xEE, spi_pin_drv=0x000000, chip_id=0x0000 (ESP32),
    # min_chip_rev=0, min_rev_full=0, max_rev_full=65535, reserved=0, hash_appended=1
    hdr = struct.pack(
        "<BBBBIB3sHBHH4sB",
        0xE9,
        len(segments),
        0x02,
        0x20,
        entry_addr,
        0xEE,
        b"\x00\x00\x00",
        0x0000,
        0x00,
        0x0000,
        0xFFFF,
        b"\x00\x00\x00\x00",
        0x01,
    )
    body = bytearray(hdr)
    seg_payloads = []
    for load_addr, data in segments:
        body.extend(struct.pack("<II", load_addr, len(data)))
        body.extend(data)
        seg_payloads.append(data)

    # Pad to next 16-byte boundary where last byte holds the XOR checksum
    pad_len = 16 - ((len(body) + 1) % 16)
    if pad_len == 16:
        pad_len = 0
    body.extend(b"\x00" * pad_len)
    body.append(compute_esp_checksum(seg_payloads))

    # Append SHA-256 over image through checksum
    digest = hashlib.sha256(body).digest()
    body.extend(digest)
    return bytes(body)


def reconstruct_xtensa_elf(segments_dir: Path, output_elf: Path) -> str:
    """Reconstruct a valid 32-bit Xtensa ELF executable from REA-extracted segments."""
    ehdr_size = 52
    phdr_size = 32
    shdr_size = 40
    num_ph = len(SEGMENTS_SPEC)

    seg_data = []
    for fname, _, _, _, _ in SEGMENTS_SPEC:
        seg_data.append((segments_dir / fname).read_bytes())

    offset = (ehdr_size + num_ph * phdr_size + 15) & ~15
    phdrs = b""
    shstrtab = b"\x00.shstrtab\x00"
    shdrs = [struct.pack("<10I", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)]
    payload = bytearray()
    cur_off = offset

    for i, (_, vaddr, flags, sname, _) in enumerate(SEGMENTS_SPEC):
        data = seg_data[i]
        filesz = len(data)
        phdrs += struct.pack("<8I", 1, cur_off, vaddr, vaddr, filesz, filesz, flags, 4)
        name_off = len(shstrtab)
        shstrtab += sname.encode() + b"\x00"
        sh_flags = 2 | (4 if (flags & 1) else 0) | (1 if (flags & 2) else 0)
        shdrs.append(struct.pack("<10I", name_off, 1, sh_flags, vaddr, cur_off, filesz, 0, 0, 4, 0))
        payload.extend(data)
        pad = (16 - (filesz % 16)) % 16
        payload.extend(b"\x00" * pad)
        cur_off += filesz + pad

    shstr_off = cur_off
    payload.extend(shstrtab)
    pad = (4 - (len(shstrtab) % 4)) % 4
    payload.extend(b"\x00" * pad)
    cur_off += len(shstrtab) + pad

    shdrs.append(struct.pack("<10I", 1, 3, 0, 0, shstr_off, len(shstrtab), 0, 0, 1, 0))
    shoff = cur_off

    ehdr = struct.pack(
        "<16sHHIIIIIHHHHHH",
        b"\x7fELF\x01\x01\x01\x00" + b"\x00" * 8,
        2,   # ET_EXEC
        94,  # EM_XTENSA
        1,
        ENTRY_ADDR,
        ehdr_size,
        shoff,
        0x300,
        ehdr_size,
        phdr_size,
        num_ph,
        shdr_size,
        len(shdrs),
        len(shdrs) - 1,
    )
    head_pad = offset - (ehdr_size + len(phdrs))
    elf_bytes = ehdr + phdrs + (b"\x00" * head_pad) + bytes(payload) + b"".join(shdrs)
    output_elf.write_bytes(elf_bytes)
    return hashlib.sha256(elf_bytes).hexdigest()


def recover_webui_assets(drom_bytes: bytes, out_webui_dir: Path, out_header_path: Path) -> None:
    """Decompress WebUI files from DROM (`segment-00.bin`) and generate `include/webFiles.h`."""
    out_webui_dir.mkdir(parents=True, exist_ok=True)
    out_header_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_header_path, "w", encoding="utf-8") as h:
        h.write("#ifndef WEB_FILES_H\n#define WEB_FILES_H\n\n#include <Arduino.h>\n\n")
        h.write("// RECOVERED FROM Bruce-CYD-2432S028.bin DROM (segment-00.bin) VIA morluto/rea\n\n")
        for var_name, filename, off, length in WEBUI_GZIP_MAP:
            blob = drom_bytes[off : off + length]
            dec = zlib.decompress(blob, 16 + zlib.MAX_WBITS)
            (out_webui_dir / filename).write_bytes(dec)
            h.write(f"const uint8_t {var_name}[] PROGMEM = {{\n")
            for i in range(0, len(blob), 15):
                chunk = ", ".join(f"0x{b:02X}" for b in blob[i : i + 15])
                h.write(f"  {chunk},\n")
            h.write("};\n\n")
            h.write(f"const uint32_t {var_name}_size = {len(blob)};\n\n")
        h.write("#endif // WEB_FILES_H\n")


def rebuild_full_flash_image(
    bootloader_path: Path,
    partition_table_path: Path,
    nvs_path: Path,
    segments_dir: Path,
    output_bin: Path,
) -> tuple[str, str]:
    """Rebuild the complete 4MB ESP32 flash image (`Bruce-CYD-2432S028.bin`) from REA components."""
    segs = []
    for fname, load_addr, _, _, _ in SEGMENTS_SPEC:
        segs.append((load_addr, (segments_dir / fname).read_bytes()))

    factory_image = build_esp_app_image(segs, ENTRY_ADDR)
    app_sha256 = factory_image[-32:].hex()

    # Assemble flash layout:
    # 0x0000 - 0x1000: 0xFF erased flash (4096 bytes)
    # 0x1000 - 0x8000: bootloader.bin (28672 bytes)
    # 0x8000 - 0x9000: partition-table.bin (4096 bytes)
    # 0x9000 - 0xF000: partitions/nvs.bin (24576 bytes)
    # 0xF000 - 0x10000: 0xFF erased flash (4096 bytes)
    # 0x10000 - 0x3C8C40: partitions/factory.bin (3902528 bytes)
    flash = bytearray(b"\xFF" * 0x10000)
    bootloader = bootloader_path.read_bytes()
    part_table = partition_table_path.read_bytes()
    nvs = nvs_path.read_bytes()

    flash[0x1000 : 0x1000 + len(bootloader)] = bootloader
    flash[0x8000 : 0x8000 + len(part_table)] = part_table
    flash[0x9000 : 0x9000 + len(nvs)] = nvs
    flash.extend(factory_image)

    output_bin.parent.mkdir(parents=True, exist_ok=True)
    output_bin.write_bytes(flash)
    flash_sha256 = hashlib.sha256(flash).hexdigest()
    return app_sha256, flash_sha256


def main() -> int:
    parser = argparse.ArgumentParser(description="REA Reverse-Engineering & Firmware Rebuilder for CYD-2432S028")
    parser.add_argument(
        "--extracted-flash",
        type=Path,
        default=Path("/tmp/bruce_bin/extracted_flash"),
        help="Path to REA extracted flash directory",
    )
    parser.add_argument(
        "--extracted-factory",
        type=Path,
        default=Path("/tmp/bruce_bin/extracted_factory"),
        help="Path to REA extracted factory segments directory",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Path to repository root",
    )
    args = parser.parse_args()

    repo_root: Path = args.repo_root
    rea_dir = repo_root / "rea_analysis"
    webui_dir = rea_dir / "extracted_webui"
    parts_dir = rea_dir / "partitions"
    parts_dir.mkdir(parents=True, exist_ok=True)

    # Copy non-app flash partitions for deterministic reconstruction
    for name, rel in [
        ("bootloader.bin", "bootloader.bin"),
        ("partition-table.bin", "partition-table.bin"),
        ("nvs.bin", "partitions/nvs.bin"),
    ]:
        src_p = args.extracted_flash / rel
        if src_p.exists():
            shutil.copy2(src_p, parts_dir / name)

    # Recover WebUI assets & include/webFiles.h from segment-00.bin (DROM)
    drom_path = args.extracted_factory / "segment-00.bin"
    if drom_path.exists():
        recover_webui_assets(
            drom_path.read_bytes(),
            webui_dir,
            repo_root / "include" / "webFiles.h",
        )
        print(f"[OK] Recovered 4 gzipped WebUI assets from DROM into {webui_dir}")

    # Reconstruct Xtensa ELF32
    elf_out = Path("/tmp/bruce_bin/Bruce-CYD-2432S028-reconstructed.elf")
    if args.extracted_factory.exists():
        elf_sha = reconstruct_xtensa_elf(args.extracted_factory, elf_out)
        print(f"[OK] Reconstructed Xtensa ELF32: {elf_out} (SHA-256: {elf_sha})")

        # Rebuild bit-exact firmware image
        rebuilt_bin = repo_root / "firmware" / "Bruce-CYD-2432S028.bin"
        app_sha, flash_sha = rebuild_full_flash_image(
            parts_dir / "bootloader.bin",
            parts_dir / "partition-table.bin",
            parts_dir / "nvs.bin",
            args.extracted_factory,
            rebuilt_bin,
        )
        print(f"[OK] Rebuilt factory app SHA-256 : {app_sha}")
        print(f"[OK] Rebuilt flash image SHA-256 : {flash_sha}")
        assert app_sha == EXPECTED_FACTORY_APP_SHA256, f"App digest mismatch: {app_sha}"
        assert flash_sha == EXPECTED_FLASH_SHA256, f"Flash digest mismatch: {flash_sha}"
        print("[VERIFIED] Bit-exact match with official Bruce-CYD-2432S028.bin!")

    return 0


if __name__ == "__main__":
    sys.exit(main())
