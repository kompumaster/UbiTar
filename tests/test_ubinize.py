"""Сверка нашего ubinize с C-версией из mtd-utils."""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from ubitar.ubi_params import read_params  # noqa: E402
from ubitar.ubinize import Layout, build_ubi  # noqa: E402

LEB = 126976
PEB = 131072


def sample(count: int) -> bytes:
    """Детерминированные данные, не сжимающиеся в ноль."""
    out = bytearray(LEB * count)
    value = 12345
    for i in range(len(out)):
        value = (value * 1103515245 + 12345) & 0x7FFFFFFF
        out[i] = value >> 16 & 0xFF
    return bytes(out)


@unittest.skipUnless(shutil.which("ubinize"), "нет ubinize в PATH")
class Parity(unittest.TestCase):
    def test_byte_for_byte(self) -> None:
        data = sample(20)
        layout = Layout(image_seq=777, vol_name="rootfs",
                        reserved_pebs=len(data) // LEB)
        mine = build_ubi(data, layout)

        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            work = Path(tmp)
            ubifs = work / "vol.ubifs"
            ubifs.write_bytes(data)
            ini = work / "vol.ini"
            ini.write_text(
                "[vol]\nmode=ubi\n"
                f"image={ubifs}\nvol_id=0\nvol_type=dynamic\n"
                f"vol_name=rootfs\nvol_alignment=1\n"
                f"vol_size={20 * LEB}\n")
            out = work / "vol.ubi"
            subprocess.run(
                ["ubinize", "-o", str(out), "-p", str(PEB), "-m", "2048",
                 "-s", "2048", "-O", "2048", "-Q", "777", str(ini)],
                check=True, capture_output=True)
            self.assertEqual(mine, out.read_bytes())

    def test_params_readable(self) -> None:
        data = bytearray(sample(4))
        data[0:4] = b"\x31\x18\x10\x06"
        struct.pack_into("<I", data, 32, 2048)
        struct.pack_into("<I", data, 36, LEB)
        struct.pack_into("<I", data, 40, 4)
        struct.pack_into("<I", data, 44, 4)
        struct.pack_into("<I", data, 80, 4)
        struct.pack_into("<H", data, 84, 2)
        data = bytes(data)
        layout = Layout(image_seq=4242, vol_name="data", reserved_pebs=4)
        image = build_ubi(data, layout)
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            path = Path(tmp) / "x.ubi"
            path.write_bytes(image)
            params = read_params(path)
        self.assertEqual(params["image_seq"], 4242)
        self.assertEqual(params["vol_name"], "data")
        self.assertEqual(params["reserved_pebs"], 4)
        self.assertEqual(params["pebs"], 6)


if __name__ == "__main__":
    unittest.main()
