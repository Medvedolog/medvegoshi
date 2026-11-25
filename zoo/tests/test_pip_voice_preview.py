import array
from pathlib import Path
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave


PREVIEW = Path(__file__).resolve().parents[1] / "tools" / "preview_pip_voice.py"


@unittest.skipUnless(shutil.which(shlex.split(os.getenv("CC", "cc"))[0]), "requires a C compiler")
class PipVoicePreviewTests(unittest.TestCase):
    def test_demo_pcm_and_named_clip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for label, events in (("demo", []), ("happy", ["happy"])):
                wav = root / (label + ".wav")
                subprocess.run([sys.executable, str(PREVIEW), str(wav), *events], check=True)
                with wave.open(str(wav), "rb") as audio:
                    self.assertEqual(
                        (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()),
                        (1, 2, 16000),
                    )
                    frames = audio.getnframes()
                    pcm = array.array("h")
                    pcm.frombytes(audio.readframes(frames))
                if sys.byteorder != "little":
                    pcm.byteswap()
                self.assertGreater(max(abs(sample) for sample in pcm), 1000)
                self.assertLess(max(abs(sample) for sample in pcm), 32000)
                self.assertEqual(set(pcm[:3520]), {0})
                self.assertEqual(set(pcm[-3520:]), {0})
                if label == "demo":
                    self.assertGreater(frames, 5 * 16000)
                    self.assertLess(frames, 10 * 16000)
                else:
                    self.assertLess(frames, 2 * 16000)

    def test_bad_event_does_not_create_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            wav = Path(directory) / "bad.wav"
            result = subprocess.run([sys.executable, str(PREVIEW), str(wav), "russian-text"],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unknown sound: russian-text", result.stderr)
            self.assertFalse(wav.exists())

    def test_existing_output_is_left_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            wav = Path(directory) / "my-take.wav"
            wav.write_bytes(b"previous take")
            result = subprocess.run([sys.executable, str(PREVIEW), str(wav), "happy"],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(wav.read_bytes(), b"previous take")


if __name__ == "__main__":
    unittest.main()
