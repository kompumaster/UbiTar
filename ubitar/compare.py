"""Сверка дерева tar с деревом, прочитанным из образа."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .tar_image import TarEntry
from .ubi_params import read_params
from .ubifs_read import iter_entries


def tar_tree(entries: list[TarEntry]) -> dict:
    by_path = {e.path: e for e in entries}

    def content(entry: TarEntry) -> bytes:
        seen = 0
        while entry.kind == "hardlink":
            entry = by_path[entry.target]
            seen += 1
            if seen > 8:
                raise ValueError("цикл hardlink")
        return entry.data or b""

    out = {}
    for entry in entries:
        common = (entry.mode, entry.uid, entry.gid)
        if entry.kind in ("file", "hardlink"):
            out[entry.path] = ("file", *common,
                               hashlib.sha256(content(entry)).hexdigest(), None)
        elif entry.kind == "link":
            out[entry.path] = ("link", *common, None, entry.target)
        else:
            out[entry.path] = (entry.kind, *common, None, None)
    return out


def image_tree(path: Path) -> tuple[dict, dict]:
    params = read_params(path)
    out = {}
    for entry in iter_entries(path, params["vol_name"]):
        digest = (hashlib.sha256(entry.data or b"").hexdigest()
                  if entry.kind == "file" else None)
        out[entry.path] = (entry.kind, entry.mode, entry.uid, entry.gid,
                           digest, entry.target)
    return params, out


def diff(want: dict, got: dict) -> list[str]:
    """Возвращает описания отличий."""
    problems = []
    for path in sorted(set(want) - set(got)):
        problems.append(f"нет в образе: {path}")
    for path in sorted(set(got) - set(want)):
        problems.append(f"лишнее в образе: {path}")
    for path in sorted(set(want) & set(got)):
        if want[path] != got[path]:
            problems.append(f"отличие: {path}: tar={want[path]} образ={got[path]}")
    return problems
