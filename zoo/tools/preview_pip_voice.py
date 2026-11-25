"""Render Pip-KeyPet's procedural nonverbal voice to a desktop WAV.

Requires Python 3 and a C99 compiler (CC, defaults to cc). No hardware,
network access or sound assets are used.
"""
import argparse
import array
import ctypes
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import wave


SOURCE = Path(__file__).resolve().parents[1] / "upstream" / "pip" / "ui"
RATE = 16000
BLOCK = 128
GAP_MS = 220
DEMO = ("poke", "happy", "oh", "sad", "growl", "purr", "nom", "yawn")


def build(directory):
    if sys.platform == "darwin":
        flags, filename = ("-dynamiclib",), "voice.dylib"
    elif os.name == "nt":
        flags, filename = ("-shared",), "voice.dll"
    else:
        flags, filename = ("-shared", "-fPIC"), "voice.so"
    library = Path(directory) / filename
    cc = shlex.split(os.environ.get("CC", "cc"))
    subprocess.run(
        [*cc, "-std=c99", "-O2", *flags, str(SOURCE / "voice.c"),
         "-o", str(library), "-lm"],
        check=True,
    )
    return library


def open_voice(library):
    voice = ctypes.CDLL(str(library))
    voice.voice_init.argtypes = (ctypes.c_int,)
    voice.voice_init.restype = None
    voice.voice_set_volume.argtypes = (ctypes.c_float,)
    voice.voice_set_volume.restype = None
    voice.voice_say.argtypes = (ctypes.c_int,)
    voice.voice_say.restype = None
    voice.voice_busy.argtypes = ()
    voice.voice_busy.restype = ctypes.c_bool
    voice.voice_name.argtypes = (ctypes.c_int,)
    voice.voice_name.restype = ctypes.c_char_p
    voice.voice_render.argtypes = (ctypes.POINTER(ctypes.c_int16), ctypes.c_int)
    voice.voice_render.restype = ctypes.c_bool
    return voice


def render_wav(library, path, events, volume=0.8, semitones=0.0):
    if not events:
        raise ValueError("provide at least one sound")
    if not (0 <= volume <= 1 and -12 <= semitones <= 12):
        raise ValueError("volume must be 0..1 and pitch -12..12 semitones")
    voice = open_voice(library)
    sounds = {}
    for i in range(64):
        name = voice.voice_name(i).decode("ascii")
        if not name:
            break
        sounds[name] = i
    unknown = set(events) - sounds.keys()
    if unknown:
        raise ValueError("unknown sound: " + ", ".join(sorted(unknown)))
    # Keep the upstream DSP verbatim. A lower internal rate raises the
    # pitch and speeds the audio when played at the fixed WAV sample rate.
    voice.voice_init(round(RATE / (2.0 ** (semitones / 12))))
    voice.voice_set_volume(volume)
    block = (ctypes.c_int16 * BLOCK)()
    gap = b"\0" * (2 * RATE * GAP_MS // 1000)
    # Finish and validate the waveform before creating the user's file;
    # exclusive creation also protects an existing take or a symlink.
    with tempfile.TemporaryFile() as complete:
        with wave.open(complete, "wb") as out:
            out.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
            out.writeframesraw(gap)
            for event in events:
                voice.voice_say(sounds[event])
                for _ in range(RATE * 8 // BLOCK):
                    voice.voice_render(block, BLOCK)
                    samples = array.array("h", block)
                    if sys.byteorder != "little":
                        samples.byteswap()
                    out.writeframesraw(samples.tobytes())
                    if not voice.voice_busy():
                        break
                else:
                    raise RuntimeError("the sound did not finish within eight seconds")
                out.writeframesraw(gap)
        complete.seek(0)
        with Path(path).open("xb") as output:
            shutil.copyfileobj(complete, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("events", nargs="*", default=DEMO, help="default: Pip's demo sounds")
    parser.add_argument("--volume", type=float, default=0.8, help="0..1 (default: 0.8)")
    parser.add_argument("--semitones", type=float, default=0.0,
                        help="host pitch/tempo experiment, -12..12 (default: original Pip)")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="pip-voice-") as directory:
            library = build(directory)
            render_wav(library, args.output, args.events, args.volume, args.semitones)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
