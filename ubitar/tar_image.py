"""Контейнер tar для дерева раздела: запись и чтение.

Формат: ustar с GNU longname для длинных имён. Служебные данные
образа лежат в `.ubitar/ubi.json`; при сборке в образ не попадают.
"""

from __future__ import annotations

import io
import json
import tarfile
from dataclasses import dataclass
from pathlib import Path

from .errors import UbiTarError
from .ubifs_read import Entry

META_DIR = ".ubitar"
META_NAME = f"{META_DIR}/ubi.json"


@dataclass
class TarEntry:
    path: str
    kind: str
    mode: int
    uid: int
    gid: int
    nlink: int
    size: int
    mtime: int
    target: str | None
    data: bytes | None


def _kind_of(info: tarfile.TarInfo) -> str:
    if info.isdir():
        return "dir"
    if info.issym():
        return "link"
    if info.islnk():
        return "hardlink"
    if info.isreg():
        return "file"
    raise UbiTarError(f"{info.name}: неподдерживаемый тип записи tar")


def write_tar(entries, meta: dict, out: Path) -> dict:
    """Пишет дерево в tar. Возвращает сводку."""
    out.parent.mkdir(parents=True, exist_ok=True)
    counts = {"file": 0, "dir": 0, "link": 0, "hardlink": 0}
    seen: dict[int, str] = {}

    with tarfile.open(out, "w", format=tarfile.GNU_FORMAT) as tf:
        payload = json.dumps(meta, ensure_ascii=False, indent=2).encode()
        info = tarfile.TarInfo(META_NAME)
        info.size = len(payload)
        info.mode = 0o644
        info.uid = 0
        info.gid = 0
        info.mtime = int(meta.get("mtime", 0))
        tf.addfile(info, io.BytesIO(payload))

        for entry in entries:
            if entry.kind in ("chr", "blk", "fifo", "sock"):
                raise UbiTarError(f"{entry.path}: устройства не поддерживаются")

            info = tarfile.TarInfo(entry.path)
            info.mode = entry.mode
            info.uid = entry.uid
            info.gid = entry.gid
            info.mtime = entry.mtime

            first = seen.get(entry.inum)
            if entry.kind == "file" and entry.nlink > 1 and first:
                info.type = tarfile.LNKTYPE
                info.linkname = first
                info.size = 0
                tf.addfile(info)
                counts["hardlink"] += 1
                continue

            if entry.kind == "dir":
                info.type = tarfile.DIRTYPE
                info.size = 0
                tf.addfile(info)
                counts["dir"] += 1
            elif entry.kind == "link":
                info.type = tarfile.SYMTYPE
                info.linkname = entry.target or ""
                info.size = 0
                tf.addfile(info)
                counts["link"] += 1
            elif entry.kind == "file":
                data = entry.data or b""
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
                counts["file"] += 1
                if entry.nlink > 1:
                    seen[entry.inum] = entry.path
            else:
                raise UbiTarError(f"{entry.path}: тип {entry.kind!r}")

    return counts


def read_tar(path: Path) -> tuple[dict, list[TarEntry]]:
    """Читает tar: метаданные образа и записи дерева."""
    meta: dict = {}
    entries: list[TarEntry] = []
    with tarfile.open(path, "r") as tf:
        for info in tf:
            if info.name == META_NAME:
                handle = tf.extractfile(info)
                meta = json.loads(handle.read().decode() if handle else "{}")
                continue
            if info.name.startswith(f"{META_DIR}/"):
                continue
            kind = _kind_of(info)
            data = None
            if kind == "file":
                handle = tf.extractfile(info)
                data = handle.read() if handle else b""
            entries.append(TarEntry(
                path=info.name,
                kind=kind,
                mode=info.mode,
                uid=info.uid,
                gid=info.gid,
                nlink=1,
                size=info.size,
                mtime=info.mtime,
                target=info.linkname if kind in ("link", "hardlink") else None,
                data=data,
            ))
    if not meta:
        raise UbiTarError(f"{path}: нет {META_NAME}")
    return meta, entries
