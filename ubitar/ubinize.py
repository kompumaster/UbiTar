"""Сборка UBI-образа из `.ubifs` (аналог `ubinize` из mtd-utils).

Повторяет формат mtd-utils 2.3.1: два PEB layout volume, затем PEB
тома. Байтовое совпадение с C-версией проверяется тестами.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from .errors import UbiTarError

EC_MAGIC = 0x55424923          # "UBI#"
VID_MAGIC = 0x55424921         # "UBI!"
UBI_VERSION = 1
DYNAMIC = 1
LAYOUT_VOL_ID = 0x7FFFFFFF - 4096
COMPAT_REJECT = 5
VTBL_RECORD_SIZE = 172
VTBL_RECORD_CRC = VTBL_RECORD_SIZE - 4
MAX_VOLUMES = 128


def crc32(data: bytes) -> int:
    """CRC32 как в mtd-utils: без финального XOR."""
    return zlib.crc32(data) ^ 0xFFFFFFFF


def _ec_header(vid_off: int, data_off: int, image_seq: int, ec: int) -> bytes:
    body = struct.pack(">IB3xQIII32x", EC_MAGIC, UBI_VERSION, ec,
                       vid_off, data_off, image_seq)
    return body + struct.pack(">I", crc32(body))


def _vid_header(vol_type: int, vol_id: int, lnum: int, compat: int = 0,
                data_size: int = 0, used_ebs: int = 0,
                data_pad: int = 0, data_crc: int = 0,
                sqnum: int = 0) -> bytes:
    body = struct.pack(
        ">IBBBBI6I4xQ12x", VID_MAGIC, UBI_VERSION, vol_type, 0, compat,
        vol_id, lnum, 0, data_size, used_ebs, data_pad, data_crc, sqnum)
    return body + struct.pack(">I", crc32(body))


def _vtbl_record(reserved_pebs: int = 0, alignment: int = 0,
                 data_pad: int = 0, vol_type: int = 0,
                 name: str = "", flags: int = 0) -> bytes:
    encoded = name.encode()
    if len(encoded) > 127:
        raise UbiTarError("имя тома длиннее 127 байт")
    body = struct.pack(">IIIBBH", reserved_pebs, alignment, data_pad,
                       vol_type, 0, len(encoded))
    body += encoded.ljust(128, b"\0") + struct.pack(">B23x", flags)
    return body + struct.pack(">I", crc32(body))


def volume_table(vol_id: int, vol_name: str, reserved_pebs: int) -> bytes:
    """Таблица томов: 128 записей, у каждой свой CRC."""
    records = bytearray(_vtbl_record() * MAX_VOLUMES)
    record = _vtbl_record(reserved_pebs=reserved_pebs, alignment=1,
                          data_pad=0, vol_type=DYNAMIC, name=vol_name)
    start = vol_id * VTBL_RECORD_SIZE
    records[start:start + VTBL_RECORD_SIZE] = record
    return bytes(records)


@dataclass
class Layout:
    peb: int = 131072
    min_io: int = 2048
    vid_off: int = 2048
    data_off: int = 4096
    image_seq: int = 0
    vol_id: int = 0
    vol_name: str = "rootfs"
    reserved_pebs: int = 0
    ec: int = 0

    @property
    def leb_size(self) -> int:
        return self.peb - self.data_off


def build_ubi(ubifs: bytes, layout: Layout, target_size: int | None = None) -> bytes:
    """Собирает UBI-образ из данных `.ubifs`."""
    leb = layout.leb_size
    if leb <= 0 or layout.peb % layout.min_io:
        raise UbiTarError("некорректная геометрия PEB/LEB")
    if len(ubifs) % leb:
        raise UbiTarError(
            f"размер .ubifs {len(ubifs)} не кратен LEB {leb}")

    used_ebs = len(ubifs) // leb
    if layout.reserved_pebs and used_ebs > layout.reserved_pebs:
        raise UbiTarError(
            f"образ занимает {used_ebs} LEB, том - {layout.reserved_pebs}")

    vtbl = volume_table(layout.vol_id, layout.vol_name,
                        layout.reserved_pebs or used_ebs)

    def peb(vid: bytes, data: bytes) -> bytes:
        if len(data) > leb:
            raise UbiTarError("LEB больше размера тома")
        out = bytearray(b"\xff" * layout.peb)
        out[0:64] = _ec_header(layout.vid_off, layout.data_off,
                               layout.image_seq, layout.ec)
        out[layout.vid_off:layout.vid_off + 64] = vid
        out[layout.data_off:layout.data_off + len(data)] = data
        return bytes(out)

    out = bytearray()
    out += peb(_vid_header(DYNAMIC, LAYOUT_VOL_ID, 0, COMPAT_REJECT), vtbl)
    out += peb(_vid_header(DYNAMIC, LAYOUT_VOL_ID, 1, COMPAT_REJECT), vtbl)

    for lnum in range(used_ebs):
        chunk = ubifs[lnum * leb:(lnum + 1) * leb]
        out += peb(_vid_header(DYNAMIC, layout.vol_id, lnum), chunk)

    if target_size is not None:
        if len(out) > target_size:
            raise UbiTarError(
                f"образ {len(out)} Б больше раздела {target_size} Б")
        out += b"\xff" * (target_size - len(out))
    return bytes(out)
