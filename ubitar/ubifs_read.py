"""Чтение UBIFS в память: записи дерева без распаковки на диск.

Нужно для `unpack`: на Windows дерево нельзя разложить в каталог
(встречаются имена, различающиеся только регистром, симлинки и
setuid), поэтому оно сразу пишется в tar.
"""

from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

from .errors import UbiTarError

KINDS = {
    stat.S_IFREG: "file",
    stat.S_IFDIR: "dir",
    stat.S_IFLNK: "link",
    stat.S_IFCHR: "chr",
    stat.S_IFBLK: "blk",
    stat.S_IFIFO: "fifo",
    stat.S_IFSOCK: "sock",
}


@dataclass(frozen=True)
class Entry:
    """Одна запись дерева."""

    path: str                 # от корня, без ведущего "/"
    inum: int                 # номер inode (для hardlink)
    kind: str                 # file|dir|link|chr|blk|fifo|sock
    mode: int                 # права, включая setuid
    uid: int
    gid: int
    nlink: int
    size: int
    mtime: int
    target: str | None = None
    data: bytes | None = None


def _open(image: Path, volume: str):
    from ubireader.ubi import ubi
    from ubireader.ubi_io import ubi_file, leb_virtual_file
    from ubireader.ubifs import ubifs

    handle = ubi_file(str(image), 131072)
    try:
        container = ubi(handle)
        if len(container.images) != 1:
            raise UbiTarError(f"{image}: ожидался один UBI-образ")
        image_obj = container.images[0]
        if volume not in image_obj.volumes:
            raise UbiTarError(f"{image}: нет тома {volume!r}")
        blocks = image_obj.volumes[volume].get_blocks(container.blocks)
        return handle, ubifs(leb_virtual_file(container, blocks))
    except Exception:
        handle.close()
        raise


def iter_entries(image: Path, volume: str):
    """Отдаёт записи дерева по одной, в порядке обхода."""
    from ubireader.ubifs import walk
    from ubireader.ubifs.misc import process_reg_file

    handle, root = _open(image, volume)
    try:
        inodes: dict = {}
        bad: list = []
        walk.index(root, root.master_node.root_lnum,
                   root.master_node.root_offs, inodes, bad)
        if bad:
            raise UbiTarError(f"{image}: повреждённый индекс, узлы {bad[:5]}")

        cache: dict[int, bytes] = {}

        def visit(inum: int, prefix: str):
            node = inodes[inum]
            for dent in node.get("dent", []):
                path = f"{prefix}/{dent.name}" if prefix else dent.name
                current = inodes[dent.inum]
                ino = current["ino"]
                kind = KINDS.get(stat.S_IFMT(ino.mode))
                if kind is None:
                    raise UbiTarError(f"{path}: неизвестный тип inode")

                target = None
                data = None
                if kind == "link":
                    target = ino.data.decode("utf-8", "surrogateescape")
                elif kind == "file":
                    if dent.inum not in cache:
                        cache[dent.inum] = process_reg_file(
                            root, current, path, inodes)
                    data = cache[dent.inum]
                elif kind in ("chr", "blk", "fifo", "sock"):
                    raise UbiTarError(f"{path}: устройства не поддерживаются")

                yield Entry(
                    path=path,
                    inum=dent.inum,
                    kind=kind,
                    mode=stat.S_IMODE(ino.mode),
                    uid=ino.uid,
                    gid=ino.gid,
                    nlink=ino.nlink,
                    size=ino.size,
                    mtime=ino.mtime_sec,
                    target=target,
                    data=data,
                )
                if kind == "dir":
                    yield from visit(dent.inum, path)

        yield from visit(1, "")
    finally:
        handle.close()
