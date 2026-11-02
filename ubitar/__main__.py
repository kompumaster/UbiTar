"""CLI ubita: разбор UBI-раздела в tar.

    python -m ubitar unpack --image system_b.bin --out system_b.tar
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import secrets

from . import __version__
from .errors import UbiTarError
from .tar_image import read_tar, write_tar
from .ubi_params import read_params
from .ubifs_read import iter_entries
from .pack import pack
from .ubinize import Layout, build_ubi


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def cmd_unpack(args) -> int:
    image = Path(args.image)
    if not image.is_file():
        print(f"error: нет образа {image}", file=sys.stderr)
        return 1
    out = Path(args.out)
    if out.exists() and not args.force:
        print(f"error: {out} уже есть; добавьте --force", file=sys.stderr)
        return 1

    params = read_params(image)
    volume = args.volume or params["vol_name"]
    if volume != params["vol_name"]:
        print(f"error: в образе том {params['vol_name']!r}, "
              f"ожидался {volume!r}", file=sys.stderr)
        return 1

    meta = {
        "schema": 1,
        "part": args.part or image.stem,
        "volume": volume,
        "part_size": image.stat().st_size,
        "peb_size": params["peb"],
        "min_io": params["sb"]["min_io"],
        "leb_size": params["sb"]["leb_size"],
        "vid_offset": params["vid_off"],
        "data_offset": params["data_off"],
        "vol_id": 0,
        "vol_type": "dynamic",
        "reserved_pebs": params["reserved_pebs"],
        "image_seq": params["image_seq"],
        "compr": params["sb"]["compr"],
        "source_sha256": sha256(image),
        "mtime": 0,
    }

    print(f"разбираю {image} (том {volume})")
    counts = write_tar(iter_entries(image, volume), meta, out)

    sidecar = out.with_suffix(out.suffix + ".json")
    sidecar.write_text(json.dumps({
        "schema": 1,
        "part": meta["part"],
        "volume": volume,
        "image": str(image),
        "tar": str(out),
        "source_sha256": meta["source_sha256"],
        "counts": counts,
        "meta": meta,
    }, ensure_ascii=False, indent=2))

    print(f"записей: файлов {counts['file']}, каталогов {counts['dir']}, "
          f"симлинков {counts['link']}, hardlinks {counts['hardlink']}")
    print(f"готово: {out}")
    return 0


def cmd_ubinize(args) -> int:
    meta = {}
    if args.meta:
        meta, _ = read_tar(Path(args.meta))
    image_seq = args.image_seq
    if image_seq is None:
        image_seq = meta.get("image_seq")
    if image_seq is None:
        image_seq = secrets.randbits(32)

    layout = Layout(
        peb=args.peb,
        min_io=args.min_io,
        vid_off=args.vid_offset,
        data_off=args.data_offset,
        image_seq=image_seq,
        vol_id=args.vol_id,
        vol_name=args.vol_name or meta.get("volume") or "rootfs",
        reserved_pebs=args.reserved_pebs or meta.get("reserved_pebs") or 0,
        ec=args.ec,
    )
    data = Path(args.ubifs).read_bytes()
    if layout.reserved_pebs == 0:
        layout.reserved_pebs = len(data) // layout.leb_size
    out = Path(args.out)
    if out.exists() and not args.force:
        print(f"error: {out} уже есть; добавьте --force", file=sys.stderr)
        return 1

    image = build_ubi(data, layout, args.part_size)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(image)
    print(f"том {layout.vol_name}: LEB {len(data) // layout.leb_size}, "
          f"image_seq {layout.image_seq}")
    print(f"готово: {out} ({len(image)} Б)")
    return 0


def cmd_pack(args) -> int:
    out = Path(args.out)
    if out.exists() and not args.force:
        print(f"error: {out} уже есть; добавьте --force", file=sys.stderr)
        return 1
    bins = Path(args.bins) if args.bins else None
    try:
        report = pack(Path(args.tar), out, args.compr, args.size, bins,
                      not args.no_verify)
    except UbiTarError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"сборщик: {report['builder']}")
    print(f"UBIFS: {report['ubifs_bytes']} Б, сжатие {report['compr']}")
    print(f"образ: {report['image_bytes']} Б (раздел {report['target_bytes']})")
    print(f"sha256: {report['image_sha256']}")
    if "checked" in report:
        print(f"сверка: записей {report['checked']}, отличий 0")
    print(f"готово: {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="ubitar", description="UBI-раздел в tar и обратно")
    ap.add_argument("--version", action="version",
                    version=f"ubitar {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    unpack = sub.add_parser("unpack", help="раздел -> tar")
    unpack.add_argument("--image", required=True)
    unpack.add_argument("--out", required=True)
    unpack.add_argument("--part", help="имя раздела для метаданных")
    unpack.add_argument("--volume", help="имя тома (по умолчанию из образа)")
    unpack.add_argument("--force", action="store_true")
    unpack.set_defaults(func=cmd_unpack)

    ubinize = sub.add_parser("ubinize", help=".ubifs -> образ раздела")
    ubinize.add_argument("--ubifs", required=True)
    ubinize.add_argument("--out", required=True)
    ubinize.add_argument("--meta", help="tar или json с параметрами тома")
    ubinize.add_argument("--peb", type=int, default=131072)
    ubinize.add_argument("--min-io", type=int, default=2048)
    ubinize.add_argument("--vid-offset", type=int, default=2048)
    ubinize.add_argument("--data-offset", type=int, default=4096)
    ubinize.add_argument("--image-seq", type=int)
    ubinize.add_argument("--vol-id", type=int, default=0)
    ubinize.add_argument("--vol-name")
    ubinize.add_argument("--reserved-pebs", type=int, default=0)
    ubinize.add_argument("--ec", type=int, default=0)
    ubinize.add_argument("--part-size", type=int)
    ubinize.add_argument("--force", action="store_true")
    ubinize.set_defaults(func=cmd_ubinize)

    pack_parser = sub.add_parser("pack", help="tar -> образ раздела")
    pack_parser.add_argument("--tar", required=True)
    pack_parser.add_argument("--out", required=True)
    pack_parser.add_argument("--compr", default="zlib",
                             choices=("none", "lzo", "zlib", "zstd",
                                      "favor_lzo"))
    pack_parser.add_argument("--size", type=int)
    pack_parser.add_argument("--bins")
    pack_parser.add_argument("--no-verify", action="store_true")
    pack_parser.add_argument("--force", action="store_true")
    pack_parser.set_defaults(func=cmd_pack)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (UbiTarError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
