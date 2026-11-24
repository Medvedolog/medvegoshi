"""Capture every MedveGoshi pet through the real game's host AMOLED V1 rig.

From the project root: python -m ports.render_zoo_gallery --out /tmp/zoo-gallery
Screens are full 368×448 game frames. No decorative text/painting, network,
persistent saves, board writes, or claim of testing a physical display.
"""
import argparse
import hashlib
import json
from pathlib import Path

from ports import amoled_v1 as v1
from ports.v1_full_game_emulate import _OPEN, _idle, _touch, emulate
from zoo import registry

DAY = 1795345200  # 2026-11-22 11:00 UTC
NIGHT = DAY + 12 * 3600
FEED = _touch(48, 259)
BATH = _touch(140, 259)
MEDICINE = _touch(187, 259)
RIGHT = _touch(205, 160)
LEFT = _touch(40, 160)

# Only ordinary game inputs and an isolated scripted starting save are used.
# Opening settings supplies the pet's actual localized name for every portrait.
SCENES = {
    "capi": ("Яйцо", "pet", 50, {"idade_min": 0}, DAY, FEED, 4, "Я в яйце!|Согрей меня!"),
    "elefante": ("Купание", "pet", 52, {"cocos": 1}, DAY, BATH, 8, "Как приятно!"),
    "pato": ("Ночь и сон", "pet", 68, {"dormindo": True}, NIGHT, FEED, 4, "Тс-с... хр-р"),
    "polvo": ("Утренняя прогулка", "explore", 50, {}, DAY - 5 * 3600, RIGHT, 10, None),
    "calopsita": ("Осмотр", "pet", 62, {}, DAY, MEDICINE, 4, "Я не болею!"),
    "cachorro": ("Кормление после обеда", "pet", 100, {}, DAY, FEED, 4, "Я уже сыт!"),
    "gato": ("Котёнок", "pet", 70, {"idade_min": 3 * 1440}, DAY, MEDICINE, 4, "Я не болею!"),
    "et": ("Прыжок на прогулке", "explore", 48, {}, DAY, RIGHT, 17, None),
    "sapinho": ("Лекарство", "pet", 60, {"doente": True, "saude": 55}, DAY, MEDICINE, 9, "Мне лучше!"),
    "pip": ("Самостоятельный режим", "companion", 66, {}, DAY + 6 * 3600, None, 12, None),
    "girafa": ("Взрослый на прогулке", "explore", 76, {}, DAY + 7 * 3600, LEFT, 12, None),
    "bjorni": ("Вечерние гуляшки", "explore", 59, {}, DAY + 8 * 3600, RIGHT, 12, None),
}
_HOLDS = ("polvo", "bjorni")


def _common(pet, food, mode, state, epoch):
    return dict(fixtures={pet: food}, initial_pet=pet, initial_mode=mode,
                fixture_state=state, fixture_epoch=epoch, screen_mode=v1.SCALE_LARGE)


def _write(output, rows, pet, kind, caption, text, image, result):
    assert image.size == (368, 448)
    assert result["native_display_windows"] == [(0, 6, 367, 440, 320160)] * result["frames"]
    assert result["offline_forced"] and result["pet"] == pet
    filename = pet + "-" + kind + ".png"
    path = output / filename
    image.save(path, optimize=True)
    rows.append({"file": filename, "id": pet, "name_ru": registry.NOMES[pet],
                 "kind": kind, "state_ru": caption, "visible_text": text,
                 "life_stage": result["life_stage"], "game_mode": result["mode"],
                 "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    (output / "gallery.json").write_text(
        json.dumps({"scope": "HOST_ONLY", "images": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(filename, caption, text, flush=True)


def render_gallery(output, pets=None, kind="all"):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    pets = registry.ELENCO if pets is None else tuple(pets)
    if set(pets) - set(SCENES):
        raise ValueError("gallery only supports the bundled set")
    rows = []
    if kind in ("all", "play"):
        for pet in pets:
            caption, mode, food, state, epoch, touch, frames, expected = SCENES[pet]
            inputs = ({},)
            if touch is not None:
                inputs += (touch,) * (frames if pet in _HOLDS else 1)
            if touch is None or pet not in _HOLDS:
                inputs += _idle(frames)
            image, result = emulate(inputs, **_common(pet, food, mode, state, epoch))
            assert result["mode"] == mode
            if expected is not None:
                # The real life engine may choose another Russian line for this
                # event. Record the one selected, never invent a caption.
                actual = result["speech"]
                if actual != expected:
                    print("actual speech", pet, repr(actual), flush=True)
                words = actual.split("|") if actual else []
            elif mode == "explore":
                words = ["Поле 1"]
                if pet == "et":
                    assert result["fake_sound_events"].count("pulo") == 1
            elif mode == "companion":
                words = ["17:00"]  # fixed scene clock, displayed by real companion HUD
            else:
                words = []
            _write(output, rows, pet, "play", caption, words, image, result)
    if kind in ("all", "portrait"):
        for pet in pets:
            image, result = emulate(_OPEN, **_common(pet, 58, "pet", {}, DAY))
            assert result["menu_opened"] and not result["menu_closed_after_open"]
            _write(output, rows, pet, "settings", "Выбор питомца",
                   ["Настройки", "Питомец", registry.NOMES[pet]], image, result)
    return rows


def main(argv=None):
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument("--out", type=Path, required=True)
    arg.add_argument("--pet", action="append", help="internal ID; may repeat")
    arg.add_argument("--kind", choices=("all", "play", "portrait"), default="all")
    opt = arg.parse_args(argv)
    render_gallery(opt.out, opt.pet, opt.kind)


if __name__ == "__main__":
    main()
