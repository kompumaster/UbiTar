"""Тесты ubita: tar и разбор раздела.

Тяжёлые проверки идут только при заданном UBITAR_IMAGE.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from ubitar import tar_image  # noqa: E402
from ubitar.errors import UbiTarError  # noqa: E402
from ubitar.ubi_params import read_params  # noqa: E402
from ubitar.ubifs_read import Entry, iter_entries  # noqa: E402

IMAGE = Path(os.environ["UBITAR_IMAGE"]) if os.environ.get("UBITAR_IMAGE") else None


class TarRoundTrip(unittest.TestCase):
    def test_write_and_read(self) -> None:
        entries = [
            Entry("etc", 2, "dir", 0o755, 0, 0, 2, 0, 100),
            Entry("etc/hosts", 3, "file", 0o644, 0, 0, 1, 5, 100,
                  data=b"127.0.0.1\n"),
            Entry("etc/link", 4, "link", 0o777, 0, 0, 1, 5, 100,
                  target="/etc/hosts"),
            Entry("bin/sh", 5, "file", 0o755, 0, 0, 2, 4, 100, data=b"busy"),
            Entry("bin/ash", 5, "file", 0o755, 0, 0, 2, 4, 100, data=b"busy"),
        ]
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            out = Path(tmp) / "tree.tar"
            counts = tar_image.write_tar(entries, {"schema": 1}, out)
            self.assertEqual(counts, {"file": 2, "dir": 1, "link": 1,
                                      "hardlink": 1})
            meta, read = tar_image.read_tar(out)
            self.assertEqual(meta, {"schema": 1})
            by_path = {e.path: e for e in read}
            self.assertEqual(by_path["etc/hosts"].data, b"127.0.0.1\n")
            self.assertEqual(by_path["etc/hosts"].mode, 0o644)
            self.assertEqual(by_path["etc/link"].target, "/etc/hosts")
            self.assertEqual(by_path["bin/ash"].kind, "hardlink")
            self.assertEqual(by_path["bin/ash"].target, "bin/sh")

    def test_meta_written(self) -> None:
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            out = Path(tmp) / "empty.tar"
            tar_image.write_tar([], {"schema": 1, "part": "x"}, out)
            meta, read = tar_image.read_tar(out)
            self.assertEqual(meta["part"], "x")
            self.assertEqual(read, [])

    def test_bad_tar(self) -> None:
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            out = Path(tmp) / "bad.tar"
            out.write_bytes(b"\0" * 1024)
            with self.assertRaises((UbiTarError, Exception)):
                tar_image.read_tar(out)


class RealImage(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if IMAGE is None or not IMAGE.is_file():
            raise unittest.SkipTest("нет UBITAR_IMAGE")
        cls.params = read_params(IMAGE)
        cls.tmp = Path(tempfile.mkdtemp(prefix="ubitar-", dir=HERE))
        cls.tar = cls.tmp / "image.tar"
        meta = {
            "schema": 1,
            "part": IMAGE.stem,
            "volume": cls.params["vol_name"],
            "part_size": cls.params["part_size"],
            "image_seq": cls.params["image_seq"],
            "reserved_pebs": cls.params["reserved_pebs"],
        }
        cls.counts = tar_image.write_tar(
            iter_entries(IMAGE, cls.params["vol_name"]), meta, cls.tar)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_meta(self) -> None:
        meta, _ = tar_image.read_tar(self.tar)
        self.assertEqual(meta["image_seq"], self.params["image_seq"])
        self.assertEqual(meta["reserved_pebs"], self.params["reserved_pebs"])
        self.assertEqual(meta["part_size"], self.params["part_size"])

    def test_symlinks_and_hardlinks(self) -> None:
        _, entries = tar_image.read_tar(self.tar)
        paths = {e.path for e in entries}
        for entry in entries:
            if entry.kind == "hardlink":
                self.assertIn(entry.target, paths)
            if entry.kind == "link":
                self.assertTrue(entry.target)

    def test_matches_extracted_tree(self) -> None:
        from .extract_ref import extract

        _, entries = tar_image.read_tar(self.tar)
        by_path = {e.path: e for e in entries}

        def content(entry):
            while entry.kind == "hardlink":
                entry = by_path[entry.target]
            return hashlib.sha256(entry.data or b"").hexdigest()

        mine = {}
        for entry in entries:
            if entry.kind in ("file", "hardlink"):
                mine[entry.path] = ("file", entry.mode, content(entry))
            elif entry.kind == "link":
                mine[entry.path] = ("link", None, entry.target)
            else:
                mine[entry.path] = (entry.kind, entry.mode, None)

        root = extract(IMAGE, self.tmp / "ref", self.params["vol_name"])
        ref = {}
        for dirpath, dirnames, filenames in os.walk(root):
            rel = Path(dirpath).relative_to(root)
            for name in dirnames + filenames:
                path = Path(dirpath) / name
                key = str(rel / name)
                st = os.lstat(path)
                if os.path.islink(path):
                    ref[key] = ("link", None, os.readlink(path))
                elif os.path.isdir(path):
                    ref[key] = ("dir", st.st_mode & 0o7777, None)
                else:
                    ref[key] = ("file", st.st_mode & 0o7777,
                                hashlib.sha256(path.read_bytes()).hexdigest())

        self.assertEqual(sorted(set(mine) - set(ref)), [])
        self.assertEqual(sorted(set(ref) - set(mine)), [])
        diff = [p for p in set(mine) & set(ref) if mine[p] != ref[p]]
        self.assertEqual(diff, [])


if __name__ == "__main__":
    unittest.main()
