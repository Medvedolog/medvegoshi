#!/usr/bin/env python3
"""No-hardware visual acceptance bundle for MedveGoshi Zoo.

Decode the REAL compiled RGB565+mask resources and check their checksums;
make contact sheets at the physical IPS/AMOLED pixel dimensions. This runs
on desktop/GitHub Actions and never needs a board or serial port.

THIS IS NOT an ESP32, ST7789 or SH8601 emulator. Memory/FPS, touch, audio,
power, and actual firmware compatibility remain NOT TESTED.
"""
import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw

from zoo.tools.preview_sprites import SIZES, decode_frame, preview


EXPECTED_GIRAFFE = (
    "normal", "happy", "sad", "sleeping",
    "sick", "surprised", "eating", "blink",
)
RUSSIAN = {
    "normal": "Обычный", "happy": "Радостный",
    "sad": "Грустный", "sleeping": "Спящий",
    "sick": "Больной", "surprised": "Удивлённый",
    "eating": "Кушает", "blink": "Моргает",
}
FORMAT = "medvegoshi-rgb565-mask-v1"


def analyze(pack, board="ips"):
    """Read/check the entire existing pack before writing any report files."""
    if board not in SIZES:
        raise ValueError("unsupported board preview")
    pack = Path(pack)
    meta = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    if meta.get("format") != FORMAT or meta.get("target") != board:
        raise ValueError("pack format or target mismatch")
    if meta.get("id") != "girafa":
        raise ValueError("this first acceptance bundle tests only the original giraffe")
    if meta.get("license") != "MIT":
        raise ValueError("expected the original MIT-licensed giraffe")
    if not meta.get("source_url") or not meta.get("source_commit"):
        raise ValueError("source provenance missing")
    frames = meta.get("frames", [])
    names = [f.get("name") for f in frames]
    if len(frames) != len(EXPECTED_GIRAFFE) or set(names) != set(EXPECTED_GIRAFFE):
        raise ValueError("giraffe pack must contain exactly 8 named expressions")

    frame_reports = []
    images = {}
    data_digests = set()
    total_bytes = 0
    for name in EXPECTED_GIRAFFE:
        im, returned = decode_frame(pack, name)
        if returned["id"] != "girafa" or im.size != tuple(meta["canvas"]):
            raise ValueError("frame dimensions differ from manifest")
        bbox = im.getchannel("A").getbbox()
        if bbox is None:
            raise ValueError("empty expression frame: " + name)
        if im.getpixel((0, 0))[3] != 0:
            raise ValueError("transparent source corner lost: " + name)
        item = next(f for f in frames if f["name"] == name)
        if tuple(item["bounds"]) != bbox:
            raise ValueError("bounding box differs from mask: " + name)
        pixel_path = pack / item["rgb565"]
        mask_path = pack / item["mask"]
        bytes_count = pixel_path.stat().st_size + mask_path.stat().st_size
        if item["bytes"] != bytes_count:
            raise ValueError("frame size differs from manifest: " + name)
        data_digests.add(item["sha256"])
        total_bytes += bytes_count
        frame_reports.append({
            "name": name, "name_ru": RUSSIAN[name],
            "sha256": item["sha256"], "bytes": bytes_count,
            "nontransparent_bounds": list(bbox),
        })
        images[name] = im

    if len(data_digests) != len(EXPECTED_GIRAFFE):
        raise ValueError("two giraffe poses are pixel-identical")
    if total_bytes != meta["bytes"]:
        raise ValueError("total pack size differs from manifest")
    if total_bytes > 768 * 1024:
        raise ValueError("pack exceeds prototype's 768 KiB budget")
    w, h = meta["canvas"]
    return {
        "status": "host_pass",
        "hardware_status": "NOT_TESTED",
        "board_preview": board,
        "board_pixels": list(SIZES[board]),
        "sprite_pixels": [w, h],
        "id": meta["id"], "license": meta["license"],
        "source_url": meta["source_url"],
        "source_commit": meta["source_commit"],
        "frame_count": len(frame_reports), "total_bytes": total_bytes,
        "frame_reports": frame_reports,
        "limits": {
            "single_rgb565_row_bytes": 2 * w,
            "single_mask_bytes": (w * h + 7) // 8,
            "framebuffer_bytes_theoretical": SIZES[board][0] * SIZES[board][1] * 2,
        },
        "not_tested": [
            "Real ESP32-S3 MicroPython / PSRAM behavior",
            "ST7789 or SH8601 display driver",
            "CST816D or FT3168 touch controller",
            "Audio / microphone / motion / RTC / battery",
            "Actual FPS, heap usage, power consumption, crash recovery",
        ],
    }


def create_bundle(pack, out, board="ips"):
    report = analyze(pack, board)
    pack = Path(pack).resolve()
    out = Path(out).resolve()
    if out == pack or pack in out.parents or out in pack.parents:
        raise ValueError("output must be independent from the input pack")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError("refusing to overwrite a non-empty QA output directory")
    out.mkdir(parents=True, exist_ok=True)
    ordered = [x["name"] for x in report["frame_reports"]]
    tile_w, tile_h = SIZES[board]
    label_height = 22
    sheet = Image.new("RGB", (tile_w * 4, (tile_h + label_height) * 2),
                      (246, 248, 251))
    for idx, name in enumerate(ordered):
        target = out / (name + ".png")
        preview(pack, target, name=name, board=board)
        with Image.open(target) as tile:
            row, col = divmod(idx, 4)
            x, y = col * tile_w, row * (tile_h + label_height)
            sheet.paste(tile.convert("RGB"), (x, y + label_height))
            ImageDraw.Draw(sheet).text((x + 6, y + 4), name.upper(),
                                       fill=(38, 51, 65))
    sheet.save(out / "all_expressions.png")
    report_json = json.dumps(report, ensure_ascii=False,
                             sort_keys=True, indent=2) + "\n"
    (out / "report.json").write_text(report_json, encoding="utf-8")
    lines = [
        "# MedveGoshi — автономная проверка Жирафика",
        "",
        "**Результат:** PASS для конвейера ресурсов на компьютере.",
        "**Аппаратная проверка:** НЕ ВЫПОЛНЕНА — ESP32 отсутствует.",
        "",
        "| Параметр | Значение |",
        "|---|---|",
        "| Режим предпросмотра | \`%s\` |" % board,
        "| Разрешение виртуального холста | %d × %d |" % tuple(SIZES[board]),
        "| Размер спрайта | %d × %d |" % tuple(report["sprite_pixels"]),
        "| Эмоции | %d / 8 |" % report["frame_count"],
        "| Размер бинарных кадров и масок | %d байт |" % report["total_bytes"],
        "| Одна строка RGB565 (оценка) | %d байт |" % report["limits"]["single_rgb565_row_bytes"],
        "| Одна маска (оценка) | %d байт |" % report["limits"]["single_mask_bytes"],
        "",
        "## Контроль эмоций",
        "",
        "| Состояние | Имя кадра | SHA256 |",
        "|---|---|---|",
    ]
    for item in report["frame_reports"]:
        lines.append("| %s | \`%s\` | \`%s\` |" %
                     (item["name_ru"], item["name"], item["sha256"][:16] + "…"))
    lines.extend([
        "",
        "![Восемь эмоций Жирафика](all_expressions.png)",
        "",
        "## Чего этот отчёт НЕ доказывает",
        "",
        "Графический предпросмотр не эмулирует ESP32-S3, ST7789, SH8601,",
        "сенсор, питание или MicroPython. Память и FPS здесь только",
        "**теоретические размеры буферов**, а не замеры устройства.",
        "Нельзя отмечать аппаратную приёмку как пройденную.",
        "",
    ])
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--board", choices=sorted(SIZES), default="ips")
    args = parser.parse_args()
    report = create_bundle(args.pack, args.out, args.board)
    print("HOST PASS: %s, %d distinct poses; hardware NOT TESTED" %
          (report["board_preview"], report["frame_count"]))


if __name__ == "__main__":
    main()
