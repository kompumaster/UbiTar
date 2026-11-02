"""Прогон по случайным UBI-образам из корпуса (по умолчанию _backup).

Корпус задаётся UBITAR_CORPUS или берётся из `_backup` рядом с
проектом. Число файлов - UBITAR_CORPUS_COUNT (по умолчанию 10),
зерно выбора - UBITAR_SEED (по умолчанию 0, чтобы прогон был
воспроизводимым).
"""

from __future__ import annotations

import os
import random
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from ubitar.ubi_params import PEB, read_params  # noqa: E402
from ubitar.tar_image import read_tar, write_tar  # noqa: E402
from ubitar.ubifs_read import iter_entries  # noqa: E402

CORPUS = Path(os.environ.get("UBITAR_CORPUS", ROOT.parent / "_backup"))
COUNT = int(os.environ.get("UBITAR_CORPUS_COUNT", "10"))
SEED = int(os.environ.get("UBITAR_SEED", "0"))
NAMES = {"system_a.bin", "system_b.bin", "data.bin", "data-legacy-624.bin"}


def candidates() -> list[Path]:
    if not CORPUS.is_dir():
        return []
    found = []
    for path in sorted(CORPUS.rglob("*.bin")):
        if path.name not in NAMES or path.parent.name != "parts":
            continue
        try:
            if path.stat().st_size % PEB:
                continue
            with path.open("rb") as stream:
                if stream.read(4) != b"UBI#":
                    continue
        except OSError:
            continue
        found.append(path)
    return found


class Corpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.files = candidates()
        if not cls.files:
            raise unittest.SkipTest(f"нет UBI-образов в {CORPUS}")
        picked = min(COUNT, len(cls.files))
        cls.sample = random.Random(SEED).sample(cls.files, picked)

    def test_unpack_sample(self) -> None:
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            work = Path(tmp)
            for index, image in enumerate(self.sample):
                with self.subTest(image=str(image)):
                    params = read_params(image)
                    self.assertIn(params["vol_name"], ("rootfs", "data"))
                    self.assertEqual(params["part_size"],
                                     image.stat().st_size)

                    tar = work / f"{index}.tar"
                    meta = {
                        "schema": 1,
                        "part": image.stem,
                        "volume": params["vol_name"],
                        "part_size": params["part_size"],
                        "image_seq": params["image_seq"],
                        "reserved_pebs": params["reserved_pebs"],
                    }
                    counts = write_tar(
                        iter_entries(image, params["vol_name"]), meta, tar)
                    total = sum(counts.values())
                    self.assertGreater(total, 0)

                    read_meta, entries = read_tar(tar)
                    self.assertEqual(read_meta["image_seq"],
                                     params["image_seq"])
                    self.assertEqual(read_meta["reserved_pebs"],
                                     params["reserved_pebs"])
                    self.assertEqual(len(entries), total)

                    paths = {e.path for e in entries}
                    for entry in entries:
                        self.assertFalse(entry.path.startswith("/"))
                        if entry.kind == "hardlink":
                            self.assertIn(entry.target, paths)
                        if entry.kind == "link":
                            self.assertTrue(entry.target)
                    tar.unlink()


if __name__ == "__main__":
    unittest.main()
