"""Сборка образа раздела из tar: tar -> .ubifs -> UBI."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .compare import diff, image_tree, tar_tree
from .errors import UbiTarError
from .tar_image import META_DIR, read_tar
from .ubinize import Layout, build_ubi

REQUIRED = ("peb_size", "min_io", "leb_size", "image_seq",
            "reserved_pebs", "part_size", "volume")

COMPRESSIONS = ("none", "lzo", "zlib", "zstd", "favor_lzo")


def builder_name() -> str:
    return "mkfs.ubifs_tar.exe" if os.name == "nt" else "mkfs.ubifs_tar"


def find_builder(bins: Path | None = None) -> Path:
    """Ищет mkfs.ubifs_tar в bins проекта, затем в PATH."""
    here = Path(__file__).resolve().parents[1]
    name = builder_name()
    for candidate in ([Path(bins) / name] if bins else []) + [here / "bins" / name]:
        if candidate.is_file():
            return candidate
    found = shutil.which(name)
    if found:
        return Path(found)
    raise UbiTarError(
        f"нет {name}: положите его в bins/ или укажите --bins/PATH")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pack(tar_path: Path, out_path: Path, compr: str = "zlib",
         size: int | None = None, bins: Path | None = None,
         verify: bool = True) -> dict:
    """Собирает образ раздела из tar и сверяет дерево."""
    if compr not in COMPRESSIONS:
        raise UbiTarError(f"неизвестное сжатие {compr!r}")
    meta, entries = read_tar(tar_path)
    missing = [key for key in REQUIRED if key not in meta]
    if missing:
        raise UbiTarError(f"{tar_path}: нет полей {', '.join(missing)}")

    builder = find_builder(bins)
    target = size or int(meta["part_size"])

    with tempfile.TemporaryDirectory(prefix="ubitar-pack-") as tmp:
        ubifs = Path(tmp) / "vol.ubifs"
        cmd = [str(builder), "--tar", str(tar_path),
               f"--tar-skip={META_DIR}",
               "-m", str(meta["min_io"]),
               "-e", str(meta["leb_size"]),
               "-c", str(meta["reserved_pebs"]),
               "-x", compr,
               "-o", str(ubifs)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            tail = (result.stdout + result.stderr).strip().splitlines()[-5:]
            raise UbiTarError(
                f"{builder.name} завершился с кодом {result.returncode}:\n"
                + "\n".join(tail))
        data = ubifs.read_bytes()

    layout = Layout(
        peb=int(meta["peb_size"]),
        min_io=int(meta["min_io"]),
        vid_off=int(meta.get("vid_offset", 2048)),
        data_off=int(meta.get("data_offset", 4096)),
        image_seq=int(meta["image_seq"]),
        vol_id=int(meta.get("vol_id", 0)),
        vol_name=str(meta["volume"]),
        reserved_pebs=int(meta["reserved_pebs"]),
    )
    image = build_ubi(data, layout, target)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(image)

    report = {
        "tar": str(tar_path),
        "out": str(out_path),
        "builder": str(builder),
        "compr": compr,
        "ubifs_bytes": len(data),
        "image_bytes": len(image),
        "target_bytes": target,
        "image_sha256": hashlib.sha256(image).hexdigest(),
    }

    if verify:
        params, got = image_tree(out_path)
        want = tar_tree(entries)
        problems = diff(want, got)
        report["checked"] = len(want)
        report["problems"] = problems
        if params["vol_name"] != layout.vol_name:
            problems.append(
                f"том {params['vol_name']!r} вместо {layout.vol_name!r}")
        if params["image_seq"] != layout.image_seq:
            problems.append("image_seq не совпал")
        if problems:
            raise UbiTarError(
                "сверка не прошла:\n" + "\n".join(problems[:20]))
    return report
