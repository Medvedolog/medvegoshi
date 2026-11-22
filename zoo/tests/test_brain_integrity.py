"""Save-integrity cases adapted as NEW MicroPython-compatible regressions.

Ideas: CyberXcyborg/ESP32-TamaPetchi test_backup.cpp (MIT).
No source is copied into this Python test. Runs on CPython.
"""
import os
import struct
import tempfile
import unittest

from companion.cerebro import Cerebro
from companion import placa as P


class BrainSaveIntegrity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = self.tmp.name + os.sep

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, age=0, seed=123):
        brain = Cerebro(seed)
        brain.idade_s = age
        P.gravar(brain, 123456, self.folder)

    def test_previous_complete_save_survives_truncation(self):
        self._write(age=14)
        self._write(age=28)   # previous complete version becomes brain.bak
        path = self.folder + P.ARQ
        with open(path, "r+b") as f:
            f.truncate(32)
        recovered = P.carregar(self.folder)
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered[0].idade_s, 14)
        self.assertEqual(recovered[0].semente, 123)

    def test_corrupt_magic_with_valid_crc_is_rejected(self):
        self._write(age=17)
        path = self.folder + P.ARQ
        with open(path, "rb") as f:
            blob = bytearray(f.read())
        blob[:4] = b"NOPE"
        blob[-4:] = struct.pack("<I", P._crc(blob[:-4]))
        with open(path, "wb") as f:
            f.write(blob)
        self.assertIsNone(P.carregar(self.folder))

    def test_valid_crc_with_truncated_payload_is_rejected(self):
        self._write(age=17)
        path = self.folder + P.ARQ
        with open(path, "rb") as f:
            blob = bytearray(f.read())
        # A bogus but internally CRC-valid record must never crash on unpack.
        blob = blob[:32] + bytearray(struct.pack("<I", 0))
        blob[-4:] = struct.pack("<I", P._crc(blob[:-4]))
        with open(path, "wb") as f:
            f.write(blob)
        self.assertIsNone(P.carregar(self.folder))


if __name__ == "__main__":
    unittest.main()
