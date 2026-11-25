"""Exercise main's optional native Pip hooks without ESP32 or user saves."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]


def wiring():
    tree = ast.parse((ROOT / "main.py").read_text())
    names = {"pip_em_uso", "pip_evento", "pip_copiar_painel", "pip_expressao"}
    nodes = [node for node in tree.body
             if ((isinstance(node, ast.FunctionDef) and node.name in names) or
                 (isinstance(node, ast.Assign) and any(
                     isinstance(target, ast.Name) and target.id == "_PIP_STATES"
                     for target in node.targets)))]
    env = {"cfg": {"personagem": "pip", "pip_native": True, "modo": "pet", "hora": "real"},
           "time": SimpleNamespace(ticks_ms=lambda: 111, ticks_diff=lambda x, y: x - y),
           "pet": {}, "pip_session": None, "pip_snapshot": None,
           "pip_reaction": None, "pip_reaction_at": 0, "lim": lambda x: x}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT / "main.py"), "exec"), env)
    return env


class PipWiringTests(unittest.TestCase):
    def test_only_selected_opted_in_real_time_care(self):
        env = wiring()
        active, cfg = env["pip_em_uso"], env["cfg"]
        self.assertTrue(active())
        for key, value in (("personagem", "girafa"), ("pip_native", False),
                           ("modo", "companion"), ("hora", "sim")):
            before = cfg[key]
            cfg[key] = value
            self.assertFalse(active())
            cfg[key] = before

    def test_feed_updates_existing_hud_and_drives_temporary_expression(self):
        env = wiring()
        state = {"needs": {"food": 0.7, "fun": 0.5, "energy": 0.8},
                 "asleep": False, "mood": "happy"}
        env["pip_snapshot"] = {"armed": True}
        events = []
        def event(name):
            events.append(name)
            return "disgusted"
        env["pip_session"] = SimpleNamespace(event=event, status=lambda: state)
        self.assertEqual(env["pip_evento"]("feed"), (True, "disgusted"))
        self.assertEqual(events, ["feed"])
        self.assertEqual(env["pet"], {"fome": 70.0, "alegria": 50.0, "energia": 80.0,
                                      "dormindo": False})
        self.assertEqual(env["pip_expressao"](576, "normal", "o"), ("susto", "triste"))
        self.assertEqual(env["pip_expressao"](1800, "normal", "o"), ("feliz", "sorriso"))

    def test_missing_module_does_not_affect_other_pets_or_write_anything(self):
        env = wiring()
        self.assertEqual(env["pip_evento"]("feed"), (False, None))
        self.assertEqual(env["pip_expressao"](100, "normal", "sorriso"), ("normal", "sorriso"))
        self.assertEqual(env["pet"], {})


if __name__ == "__main__":
    unittest.main()
