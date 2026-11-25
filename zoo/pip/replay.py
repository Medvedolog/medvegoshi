"""Replay Pip on CPython with a fixed clock, seed, and isolated save slot."""

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from zoo.pip.host_save import load_state, save_state
from zoo.pip.pet_host import EVENTS, Pet


DEFAULT_START = 1795377600  # 2026-11-22 20:00:00 UTC
MAX_STEPS = 128
MAX_ELAPSED = 31 * 24 * 3600
MAX_SCENARIO_BYTES = 64 * 1024
REASON_LABELS = {
    "asleep": "спит",
    "rare": "редкая реакция",
    "body": "потребность",
    "after": "реакция на событие",
    "urge": "хочет действия",
    "night": "ночное состояние",
    "situation": "ситуация",
    "palette": "естественная смена настроения",
}
EVENT_LABELS = {"feed": "покормить", "stroke": "погладить",
                "sleep": "уложить спать", "wake": "разбудить"}
EVENT_REASONS = {
    ("feed", "nauseous"): ("fed_while_full", "Пип уже был сыт"),
    ("feed", "disgusted"): ("fed_again_while_full", "покормили сытым повторно"),
    ("feed", "content"): ("ate_with_appetite", "он поел с аппетитом"),
    ("stroke", None): ("affection", "ласка повышает привязанность"),
    ("sleep", None): ("bedtime_requested", "его уложили спать"),
    ("wake", "surprised"): ("woken_rested", "проснулся отдохнувшим"),
    ("wake", "annoyed"): ("woken_tired", "его разбудили уставшим"),
    ("wake", "indignant"): ("woken_again", "его разбудили повторно"),
}

MOOD_LABELS = {
    "neutral": "спокоен", "happy": "рад", "sad": "грустит", "angry": "сердится",
    "surprised": "удивлён", "sleepy": "сонный", "asleep": "спит",
    "skeptical": "сомневается", "curious": "любопытствует", "love": "растроган",
    "dizzy": "голова кружится", "ouch": "ой!", "stoned": "завис",
    "pinkeye": "глаз покраснел", "nauseous": "подташнивает", "sick": "болеет",
    "tired": "устал", "exhausted": "без сил", "annoyed": "раздражён",
    "furious": "в ярости", "rage": "в бешенстве", "swearing": "ворчит",
    "indignant": "возмущён", "belligerent": "воинственен",
    "hurt": "обижен", "disgusted": "противно", "suspicious": "подозревает неладное",
    "cynical": "усмехается", "afraid": "напуган", "nervous": "нервничает",
    "despondent": "приуныл", "lonely": "скучает по тебе", "gloomy": "хмурится",
    "dull": "вялый", "shy": "стесняется", "smug": "доволен собой",
    "bored": "скучает", "shocked": "в шоке", "dismayed": "расстроен",
    "puzzled": "недоумевает", "amazed": "в восторге", "cheeky": "озорничает",
    "content": "доволен", "comfy": "ему уютно", "yes": "да", "no": "нет",
}
DETAIL_LABELS = {
    "asleep": "заснул", "waking": "только проснулся", "walking": "на прогулке",
    "charging": "заряжается", "food_critical": "очень голоден", "food_low": "хочет есть",
    "energy_critical": "совсем нет сил", "energy_low": "устал",
    "love_critical": "очень одиноко", "love_low": "не хватает внимания",
    "fun_low": "скучно", "walk_low": "хочется гулять", "tired_at_night": "устал за день",
    "battery_empty": "батарея почти пуста", "battery_tired": "мало заряда",
    "battery_low": "садится батарея", "multiple_needs": "сразу несколько потребностей",
    "win": "победа", "lose": "поражение", "record": "новый рекорд", "fright": "испуг",
    "flood": "слишком много уведомлений", "sulk": "обиделся", "missed": "соскучился",
    "fed_up": "ему надоело", "great": "всё отлично", "good": "всё хорошо",
    "neutral": "обычный день", "low": "день не задался",
    "evening_great": "отличный вечер", "evening_good": "хороший вечер",
    "evening_neutral": "обычный вечер", "evening_low": "вечер не задался",
}
NEED_LABELS = {"food": "сытость", "energy": "энергия", "fun": "веселье",
               "love": "внимание", "walk": "прогулка"}

# after_s is a delta from the preceding row, not from the start.
DEFAULT_STEPS = (
    {"after_s": 0, "op": "observe"},
    {"after_s": 60, "op": "event", "name": "feed"},
    {"after_s": 60, "op": "event", "name": "stroke"},
    {"after_s": 2 * 3600, "op": "event", "name": "sleep"},
    {"after_s": 0, "op": "checkpoint"},
    {"after_s": 10 * 3600, "op": "observe"},
    {"after_s": 0, "op": "event", "name": "wake"},
    {"after_s": 60, "op": "observe"},
)


def validate_steps(steps):
    if not isinstance(steps, (list, tuple)) or not 1 <= len(steps) <= MAX_STEPS:
        raise ValueError("scenario must contain 1..%d steps" % MAX_STEPS)
    canonical = []
    elapsed = 0
    for pos, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            raise ValueError("step %d must be an object" % pos)
        op = step.get("op")
        if op not in ("observe", "event", "checkpoint"):
            raise ValueError("step %d: unknown op" % pos)
        expected = {"after_s", "op", "name"} if op == "event" else {"after_s", "op"}
        if set(step) != expected:
            raise ValueError("step %d: expected only %s" % (pos, ", ".join(sorted(expected))))
        delay = step["after_s"]
        if type(delay) is not int or delay < 0:
            raise ValueError("step %d: after_s must be a nonnegative integer" % pos)
        elapsed += delay
        if elapsed > MAX_ELAPSED:
            raise ValueError("step %d: scenario exceeds a total of 31 days" % pos)
        row = {"after_s": delay, "op": op}
        if op == "event":
            raw = step["name"]
            name = raw.replace("-", "_") if isinstance(raw, str) else None
            if name not in EVENTS:
                raise ValueError("step %d: unknown Pip event %r" % (pos, raw))
            row["name"] = name
        canonical.append(row)
    return canonical


def load_scenario(path):
    with Path(path).open("rb") as source:
        raw = source.read(MAX_SCENARIO_BYTES + 1)
    if len(raw) > MAX_SCENARIO_BYTES:
        raise ValueError("scenario JSON exceeds %d bytes" % MAX_SCENARIO_BYTES)
    steps = json.loads(raw.decode("utf-8"))
    if not isinstance(steps, list):
        raise ValueError("scenario JSON must be an array")
    return validate_steps(steps)


def replay(steps=DEFAULT_STEPS, *, seed=1, start=DEFAULT_START, tz_min=0):
    """Return stable trace rows, always using a temporary Pip-only save slot.

    After a checkpoint the restored pet drives the trace; a distinct live
    instance receives the same future inputs to catch lost state or RNG.
    """
    steps = validate_steps(steps)
    pet = Pet(seed=seed, now=start, tz_min=tz_min)
    reference = None
    now = start
    rows = []
    checkpoints = 0
    verified_steps = 0
    with TemporaryDirectory(prefix="medve-pip-replay-") as temp:
        slot = Path(temp) / "pip-state.json"
        for index, step in enumerate(steps, 1):
            delay = step["after_s"]
            if delay:
                now += delay
                pet.update(now)
                if reference is not None:
                    reference.update(now)

            op = step["op"]
            reaction = None
            if op == "event":
                reaction = pet.event(step["name"])
                if reference is not None and reaction != reference.event(step["name"]):
                    raise RuntimeError("checkpoint reaction diverged at step %d" % index)
            if reference is not None:
                if (pet.explain() != reference.explain() or
                        pet.snapshot() != reference.snapshot()):
                    raise RuntimeError("checkpoint state diverged at step %d" % index)
                verified_steps += 1
            row = {"step": index, "elapsed_s": now - start, "op": op}
            if op == "event":
                row.update(event=step["name"], reaction=reaction)
                explanation = EVENT_REASONS.get((step["name"], reaction))
                if explanation is not None:
                    row["reaction_reason"] = explanation[0]
            elif op == "checkpoint":
                payload = pet.snapshot()
                save_state(slot, payload)
                reference, pet = pet, Pet.restore(load_state(slot))
                if pet.snapshot() != payload or pet.explain() != reference.explain():
                    raise RuntimeError("checkpoint roundtrip failed at step %d" % index)
                checkpoints += 1
                row["roundtrip"] = "identical"
            row["state"] = deepcopy(pet.explain())
            rows.append(row)

    return {"engine": "pip-host", "seed": seed, "start": start, "tz_min": tz_min,
            "checkpoints": checkpoints, "verified_steps": verified_steps, "steps": rows}


def _human(report):
    lines = ["Pip: детерминированный прогон, seed=%d, старт=%d, UTC%+d мин."
             % (report["seed"], report["start"], report["tz_min"])]
    for row in report["steps"]:
        state, when = row["state"], row["elapsed_s"]
        hour, remainder = divmod(when, 3600)
        minute, second = divmod(remainder, 60)
        action = row["op"]
        if action == "event":
            action = EVENT_LABELS.get(row["event"], row["event"])
            if row["reaction"]:
                action += " → " + MOOD_LABELS.get(row["reaction"], row["reaction"])
            explanation = EVENT_REASONS.get((row["event"], row["reaction"]))
            if explanation is not None:
                action += " [%s]" % explanation[1]
        elif action == "checkpoint":
            action = "сохранение → загрузка: совпало"
        else:
            action = "наблюдение"
        reason = state["reason"]
        detail = REASON_LABELS.get(reason["kind"], reason["kind"])
        lines.append("+%02d:%02d:%02d  %s | %s: %s (%s)"
                     % (hour, minute, second, action,
                        MOOD_LABELS.get(state["mood"], state["mood"]), detail,
                        DETAIL_LABELS.get(reason["detail"], reason["detail"])))
        lines.append("          " + ", ".join("%s=%.0f%%" % (NEED_LABELS.get(k, k), v * 100)
                                                for k, v in state["needs"].items()))
    lines.append("Проверок сохранения: %d; совпавших шагов: %d."
                 % (report["checkpoints"], report["verified_steps"]))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path,
                        help="optional JSON array of {after_s, op, name?} steps")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--start", type=int, default=DEFAULT_START,
                        help="initial Unix time in seconds")
    parser.add_argument("--tz-min", type=int, default=0, help="local offset in minutes")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of readable text")
    args = parser.parse_args(argv)
    try:
        steps = load_scenario(args.scenario) if args.scenario else DEFAULT_STEPS
        report = replay(steps, seed=args.seed, start=args.start, tz_min=args.tz_min)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(2, "%s: %s\n" % (parser.prog, exc))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(_human(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
