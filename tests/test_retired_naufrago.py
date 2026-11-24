"""Host-only verification of the legacy pet roster and save guard."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ("capi", "elefante", "pato", "polvo", "calopsita",
          "cachorro", "gato", "et", "sapinho")
BOOT = r'''
import builtins, runpy, sys, time, types
entry, selected = sys.argv[1:]
sys.path.insert(0, str(__import__("pathlib").Path(entry).parent / "previa"))
real_open = builtins.open
opened = []
def track(path, mode="r", *args, **kwargs):
    opened.append((str(path), mode))
    return real_open(path, mode, *args, **kwargs)
builtins.open = track
if selected == "naufrago":
    try:
        runpy.run_path(entry, run_name="_guard_probe")
    except RuntimeError as exc:
        assert "Naufrago removido" in str(exc) and "sem apagar a flash" in str(exc), exc
    else:
        raise AssertionError("retired pet unexpectedly booted")
    assert opened == [("config.json", "r")], opened
    assert not {"machine", "hw", "rede", "desenho", "vida"} & sys.modules.keys()
else:
    time.ticks_ms = lambda: 10000
    time.ticks_add = lambda a, b: a + b
    time.ticks_diff = lambda a, b: a - b
    fb = sys.modules["framebuf"] = types.ModuleType("framebuf")
    fb.FrameBuffer = lambda *args: object()
    fb.MONO_HLSB, fb.RGB565 = 1, 2
    state = runpy.run_path(entry, run_name="_supported_probe")
    d, vida, rede = state["d"], state["V"], state["rede"]
    active = ("capi", "elefante", "pato", "polvo", "calopsita",
              "cachorro", "gato", "et", "sapinho")
    assert d.ELENCO == active
    for rows in (d.NOMES, d.HTOP, d._FUNCS, vida.NOMES, vida.HTOP, vida.FRASES_CHAR):
        assert set(rows) == set(active), rows.keys()
    assert not hasattr(d, "naufrago")
    assert state["cfg"]["personagem"] == selected
    assert state["pet"]["fome"] == 41

    # On-air compatibility: pings carry the actual string ID, not an
    # index in the menu. An older peer remains visible to the protocol.
    mac = b"123456"
    class Radio:
        peers_table = {mac: [-35]}
        def __init__(self):
            self.recv_queue = [(mac, b"CGPnaufrago"), (mac, b"CGPnaufrago")]
            self.sent = []
        def recv(self, timeout):
            return self.recv_queue.pop(0) if self.recv_queue else (None, None)
        def send(self, addr, msg, sync):
            self.sent.append((addr, msg, sync))
    rede.en = Radio()
    events = []
    rede._ouvir(10000, events)
    rede._falar(10000, selected, True, events)
    assert events == [("chegou", "naufrago")], events
    assert rede.en.sent == [(rede.TODOS, b"CGP" + selected.encode(), False)]
    assert rede.PRESENTES == ("caixa", "flor", "coracao", "estrela", "bola", "capim")
'''


class RetiredPetTests(unittest.TestCase):
    def _boot(self, selected):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            saves = {
                "config.json": json.dumps({"personagem": selected, "modo": "companion"}).encode(),
                "capi.json": b'{"fome":41,"idade_min":9300}',
                "brain.bin": b"CAPI\x00\x12\xfe\xff",
                "brain.bak": b"previous good copy",
                "brain.tmp": b"interrupted older write",
            }
            for name, data in saves.items():
                (root / name).write_bytes(data)
            times = {name: (root / name).stat().st_mtime_ns for name in saves}
            env = dict(os.environ, PYTHONPATH=str(ROOT))
            result = subprocess.run(
                [sys.executable, "-c", BOOT, str(ROOT / "main.py"), selected],
                cwd=root, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
            self.assertEqual({path.name for path in root.iterdir()}, saves.keys())
            for name, data in saves.items():
                self.assertEqual((root / name).read_bytes(), data, name)
                self.assertEqual((root / name).stat().st_mtime_ns, times[name], name)

    def test_retired_selection_stops_before_save_reads_or_hardware_imports(self):
        self._boot("naufrago")

    def test_supported_selection_keeps_its_save_and_original_radio_id(self):
        for pet in ACTIVE:
            with self.subTest(pet=pet):
                self._boot(pet)


if __name__ == "__main__":
    unittest.main()
