# ubitar: UBI-раздел в tar и обратно

Инструмент для преобразования UBI-раздела в tar и обратной сборки.
Разбор работает на чистом Python, без Linux-утилит.

Состояние: `unpack` (раздел -> tar), `ubinize` (.ubifs -> UBI) и
`pack` (tar -> раздел) готовы, со сверкой дерева.

## Зачем tar

Дерево файловой системы нельзя разложить в каталог на Windows:

- встречаются имена, различающиеся только регистром, а NTFS их не
  различает;
- симлинки;
- setuid-файлы и gid, отличный от 0.

tar хранит mode, uid, gid, mtime, симлинки, hardlinks и устройства,
поэтому подходит как промежуточный формат.

## Установка

```
python3 -m pip install -r requirements.txt
```

Нужен Python 3.9+ (проверено на 3.14) и `ubi_reader` (чистый Python).
Запускать из корня репозитория: `python -m ubitar ...`.

## Разбор

```
python -m ubitar unpack --image part.bin --out part.tar
```

Результат:

- `part.tar` - дерево с метаданными;
- `part.tar.json` - сводка: счётчики, хеш источника, параметры.

Служебные данные образа лежат в архиве, в `.ubitar/ubi.json`:
размер раздела и PEB, `image_seq`, имя тома, `reserved_pebs`,
сжатие. При сборке этот каталог в образ не попадает.

## Сборка UBI

```
python -m ubitar ubinize --ubifs rootfs.ubifs --out part.bin \
    --image-seq 12345 --vol-name rootfs --reserved-pebs 468
```

Параметры можно взять из tar: `--meta part.tar`. Результат
побайтово совпадает с C-версией `ubinize` из mtd-utils 2.3.1,
это проверяется тестом.

## Сборка раздела из tar

```
python -m ubitar pack --tar part.tar --out part.bin
```

Параметры берутся из `.ubitar/ubi.json`, сборка идёт через
`bins/mkfs.ubifs_tar` (Windows - `.exe`), затем встроенный
`ubinize`, образ дополняется `0xFF` до размера раздела.

Служебный каталог `.ubitar/` в образ не попадает: `pack` передаёт
сборщику `--tar-skip=.ubitar`.

По умолчанию после сборки дерево сверяется с tar: пути, типы, mode,
uid, gid, содержимое, симлинки. Отличие - ошибка. `--no-verify`
отключает сверку, `--compr` меняет сжатие (`zlib` по умолчанию).

## Формат tar

`ustar` с GNU longname для длинных имён. Каждая запись - обычный
элемент tar: тип, mode, uid, gid, mtime, размер, цель симлинка или
hardlink. Ничего своего, кроме `.ubitar/ubi.json`.

## mkfs.ubifs для Windows

`mkfs.ubifs` остаётся на C. В форке mtd-utils добавлен режим
`--tar FILE`: дерево берётся из архива, включая mode, uid, gid,
симлинки и hardlinks. Форк:
https://github.com/kompumaster/mtd-utils-tar.

Готовые сборки лежат в `bins/`:
`mkfs.ubifs_tar.exe` (Windows) и `mkfs.ubifs_tar` (Linux). Суффикс
`_tar` отличает их от системной утилиты. `pack --bins PATH` указывает
другой каталог; иначе UbiTar ищет `bins/`, затем `PATH`.

## Ограничения

- PEB 131072 Б, VID offset 2048, data offset 4096 — другой layout не
  поддерживается;
- один том UBIFS с `vol_id = 0`;
- образ читается в память целиком;
- tar считается доверенным: контрольная сумма не проверяется;
- zstd-образы читает только ядро 5.9 и новее;
- Windows-бинарник требует UCRT (Windows 10 и новее).

## Тесты

```
UBITAR_IMAGE=part.bin python -m unittest discover -s tests -t . -v
```

Без `UBITAR_IMAGE` тяжёлые проверки пропускаются, остаются тесты
формата. Корпус для `test_corpus` задаётся `UBITAR_CORPUS`
(по умолчанию `../_backup`).

## Состояние

Круговой путь «раздел → tar → раздел» на реальном образе дал 0
отличий. `unpack`, `ubinize`, `pack` и сверка дерева работают на
Linux и Windows.

## Лицензия

GPL-2.0, см. `LICENSE`.
