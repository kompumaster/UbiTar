# bins: готовые бинарники mkfs.ubifs_tar

Здесь лежат собранные `mkfs.ubifs_tar` для Linux и Windows, чтобы не
искать их по системе. Это не системная `mkfs.ubifs`, а сборка из
форка mtd-utils с режимом `--tar`; имя с `_tar` не путается с
системной утилитой.

| Файл | Что | Размер | SHA-256 |
|---|---|---:|---|
| `mkfs.ubifs_tar` | Linux x86-64, `--tar`, zlib/lzo/zstd | 334 664 | `c426898f827bb91560434fe13de3ca8027432deb19947d38783be7e1fe813e70` |
| `mkfs.ubifs_tar.exe` | Windows x86-64, `--tar`, zlib/lzo/zstd | 996 366 | `c825d45384da5895be76376589870be2150ec6e3d4a8bfe4d001d1fd566a6261` |

Источник: `https://github.com/kompumaster/mtd-utils-tar`,
ветка `tar-mode`, коммит `f5085113912eebe1795663642adfdd35ddb3f3d9`. Сборка — `win32/build-linux.sh`
и `win32/build-mingw.sh`; бинарники очищены `strip`, debug-информации
и локальных путей сборки в них нет.

## Режимы

- `--tar=FILE` — читать дерево из архива;
- `--tar-skip=PATH` — не включать путь и его потомков в образ; флаг
  можно повторять. `pack` передаёт `--tar-skip=.ubitar`;
- сжатие: `-x zlib`, `-x lzo`, `-x favor_lzo`, `-x zstd`; по
  умолчанию `zlib`. zstd-образы читает только ядро 5.9 и новее, для
  старых ядер используйте zlib или lzo.

## Зависимости

- Linux: `libz.so.1`, `liblzo2.so.2`, `libzstd.so.1`, `libuuid.so.1`;
- Windows: только UCRT (Windows 10 и новее), MinGW-библиотеки
  вкомпилированы статически.

UbiTar ищет бинарник в `bins/`, затем в `PATH`.

Бинарники собраны из GPL-2.0 исходников mtd-utils; исходники, патч
`--tar` и способ пересборки — в форке по ссылке выше.
