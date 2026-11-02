"""Параметры UBI/UBIFS из образа (без внешних утилит)."""

from __future__ import annotations

import struct
from pathlib import Path

from .errors import UbiTarError

PEB = 131072
MIN_IO = 2048
SUB_PAGE = 2048
VID_OFF = 2048
LEB = 126976
LAYOUT_VOL_ID = 0x7FFFEFFF


def read_params(image: Path) -> dict:
    """Читает параметры тома из UBI-образа."""
    data = image.read_bytes()
    if len(data) < PEB or len(data) % PEB:
        raise UbiTarError(f"{image}: размер {len(data)} Б не кратен PEB")
    if data[:4] != b"UBI#":
        raise UbiTarError(f"{image}: нет сигнатуры UBI")

    pebs = len(data) // PEB
    vid_off = data_off = seq = None
    layout = None
    sb = None

    for i in range(pebs):
        base = i * PEB
        if data[base:base + 4] != b"UBI#":
            continue
        v_off, d_off = struct.unpack(">II", data[base + 16:base + 24])
        if vid_off is None:
            vid_off, data_off = v_off, d_off
            seq = struct.unpack(">I", data[base + 24:base + 28])[0]
        vid = data[base + v_off:base + v_off + 64]
        if vid[:4] != b"UBI!":
            continue
        vol_id, lnum = struct.unpack(">II", vid[8:16])
        if vol_id == LAYOUT_VOL_ID and lnum == 0:
            rec = data[base + d_off:base + d_off + 172]
            name_len = struct.unpack(">H", rec[14:16])[0]
            layout = {
                "peb": i,
                "reserved_pebs": struct.unpack(">I", rec[0:4])[0],
                "name": rec[16:16 + name_len].decode("utf-8", "replace"),
                "type": rec[12],
            }
        if vol_id == 0 and lnum == 0:
            node = data[base + d_off:base + d_off + 96]
            if node[:4] != b"\x31\x18\x10\x06":
                raise UbiTarError(f"{image}: не найден суперблок UBIFS")
            sb = {
                "min_io": struct.unpack("<I", node[32:36])[0],
                "leb_size": struct.unpack("<I", node[36:40])[0],
                "leb_cnt": struct.unpack("<I", node[40:44])[0],
                "max_leb_cnt": struct.unpack("<I", node[44:48])[0],
                "fmt_version": struct.unpack("<I", node[80:84])[0],
                "compr": struct.unpack("<H", node[84:86])[0],
            }

    if layout is None:
        raise UbiTarError(f"{image}: не найден layout volume UBI")
    if sb is None:
        raise UbiTarError(f"{image}: не найден том 0 с суперблоком UBIFS")
    if vid_off != VID_OFF or data_off != 4096:
        raise UbiTarError(
            f"{image}: смещения заголовков vid={vid_off}, data={data_off}")
    return {
        "peb": PEB, "pebs": pebs, "part_size": len(data),
        "vid_off": vid_off, "data_off": data_off, "image_seq": seq,
        "vol_name": layout["name"], "reserved_pebs": layout["reserved_pebs"],
        "vol_type": layout["type"], "sb": sb,
    }
