"""Тесты сборки: tar -> .ubifs -> образ раздела."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from ubitar.errors import UbiTarError  # noqa: E402
from ubitar.pack import find_builder, pack  # noqa: E402
from ubitar.tar_image import read_tar, write_tar  # noqa: E402
from ubitar.ubifs_read import Entry, iter_entries  # noqa: E402

PEB = 131072
LEB = 126976
PART = 20 * PEB
IMAGE = Path(os.environ["UBITAR_IMAGE"]) if os.environ.get("UBITAR_IMAGE") else None


def have_builder() -> bool:
    try:
        find_builder()
        return True
    except UbiTarError:
        return False


def sample_entries() -> list[Entry]:
    return [
        Entry("etc", 2, "dir", 0o755, 0, 0, 2, 0, 1600000000),
        Entry("etc/hosts", 3, "file", 0o644, 0, 102, 1, 12,
              1600000000, data=b"127.0.0.1\n"),
        Entry("etc/link", 4, "link", 0o777, 0, 0, 1, 0,
              1600000000, target="/etc/hosts"),
        Entry("bin", 5, "dir", 0o755, 0, 0, 2, 0, 1600000000),
        Entry("bin/su", 6, "file", 0o4755, 0, 0, 1, 4,
              1600000000, data=b"suid"),
        Entry("bin/su2", 6, "file", 0o4755, 0, 0, 2, 4,
              1600000000, data=b"suid"),
    ]


def sample_meta() -> dict:
    return {
        "schema": 1,
        "part": "test",
        "volume": "rootfs",
        "part_size": PART,
        "peb_size": PEB,
        "min_io": 2048,
        "leb_size": LEB,
        "vid_offset": 2048,
        "data_offset": 4096,
        "vol_id": 0,
        "type": "dynamic",
        "reserved_pebs": 32,
        "image_seq": 424242,
        "compr": 2,
        "mtime": 0,
    }


@unittest.skipUnless(have_builder(), "нет mkfs.ubifs_tar")
class Synthetic(unittest.TestCase):
    def test_pack_and_verify(self) -> None:
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            work = Path(tmp)
            tar = work / "part.tar"
            write_tar(sample_entries(), sample_meta(), tar)
            out = work / "part.bin"
            report = pack(tar, out, compr="zlib")
            self.assertEqual(report["problems"], [])
            self.assertEqual(report["checked"], 6)
            self.assertEqual(out.stat().st_size, PART)
            self.assertEqual(report["image_bytes"], PART)

            meta, entries = read_tar(tar)
            self.assertEqual(len(entries), 6)
            got = {e.path: e for e in iter_entries(out, "rootfs")}
            self.assertEqual(got["bin/su"].mode & 0o7777, 0o4755)
            self.assertEqual(got["etc/link"].target, "/etc/hosts")
            self.assertEqual(got["etc/hosts"].gid, 102)

    def test_pack_without_meta(self) -> None:
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            work = Path(tmp)
            tar = work / "bad.tar"
            write_tar(sample_entries(), {"schema": 1}, tar)
            with self.assertRaises(UbiTarError):
                pack(tar, work / "x.bin")

    def test_unknown_compression(self) -> None:
        with self.assertRaises(UbiTarError):
            pack(Path("x.tar"), Path("x.bin"), compr="brotli")


@unittest.skipUnless(IMAGE and IMAGE.is_file(), "нет UBITAR_IMAGE")
@unittest.skipUnless(have_builder(), "нет mkfs.ubifs_tar")
class RealImage(unittest.TestCase):
    def test_round_trip(self) -> None:
        from ubitar.__main__ import main as cli

        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            work = Path(tmp)
            tar = work / "part.tar"
            code = cli(["unpack", "--image", str(IMAGE), "--out", str(tar)])
            self.assertEqual(code, 0)
            out = work / "part.bin"
            report = pack(tar, out, compr="zlib")
            self.assertEqual(report["problems"], [])
            self.assertGreater(report["checked"], 1000)


if __name__ == "__main__":
    unittest.main()
