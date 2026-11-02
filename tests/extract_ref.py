"""Извлечение тома UBI в каталог - эталон для сверки тестов."""

from __future__ import annotations

import os
from pathlib import Path


def extract(image: Path, outdir: Path, volume: str) -> Path:
    from ubireader.ubi import ubi
    from ubireader.ubi_io import ubi_file, leb_virtual_file
    from ubireader.ubifs import ubifs
    from ubireader.ubifs import output

    def chmod_only(path, inode):
        if not os.path.islink(path):
            os.chmod(path, inode["ino"].mode & 0o7777)

    output._set_file_perms = chmod_only
    outdir.mkdir(parents=True, exist_ok=True)
    handle = ubi_file(str(image), 131072)
    try:
        container = ubi(handle)
        for image_obj in container.images:
            if volume not in image_obj.volumes:
                continue
            blocks = image_obj.volumes[volume].get_blocks(container.blocks)
            target = outdir / str(image_obj.image_seq) / volume
            target.mkdir(parents=True, exist_ok=True)
            output.extract_files(ubifs(leb_virtual_file(container, blocks)),
                                 str(target), perms=True)
            return target
    finally:
        handle.close()
    raise RuntimeError(f"в образе {image} нет тома {volume!r}")
