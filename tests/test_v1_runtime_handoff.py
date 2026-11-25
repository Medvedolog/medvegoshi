import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

from ports import amoled_v1_launch, runtime_handoff


def profile(profile_id="amoled_1_8_v1", rtc_write=False):
    return SimpleNamespace(profile_id=profile_id, capabilities={"rtc_write": rtc_write},
                           i2c=None, tela=None, toque=None, mov=None, relogio=None,
                           som=None, bateria=None, botao=None)


class RuntimeHandoffTest(unittest.TestCase):
    def tearDown(self):
        runtime_handoff.clear()

    def test_stock_import_has_no_pending_v1_and_stage_is_single_use(self):
        self.assertIsNone(runtime_handoff.take())
        use = profile()
        runtime_handoff.stage(use)
        with self.assertRaises(RuntimeError):
            runtime_handoff.stage(use)
        self.assertEqual(runtime_handoff.take(), (use, False))
        self.assertIsNone(runtime_handoff.take())

    def test_other_plat_and_v1_clock_write_are_refused(self):
        for bad in (profile("amoled-v2"), profile(rtc_write=True), object()):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                runtime_handoff.stage(bad)
        self.assertIsNone(runtime_handoff.take())
        with self.assertRaisesRegex(RuntimeError, "confirmation"):
            amoled_v1_launch.run(enabled=True)

    def test_explicit_loader_confirms_profile_and_clean_failure(self):
        use = profile()

        def fake_first(name):
            self.assertEqual(name, "v1_game_app")
            self.assertEqual(runtime_handoff.take(), (use, False))
            return SimpleNamespace(runtime_profile_id="amoled_1_8_v1", principal=lambda: "ran")

        self.assertEqual(amoled_v1_launch._launch(use, False, fake_first), "ran")
        with self.assertRaisesRegex(RuntimeError, "did not accept"):
            amoled_v1_launch._launch(use, False,
                lambda _: SimpleNamespace(principal=lambda: self.fail("unsafe fallback")))
        self.assertIsNone(runtime_handoff.take())

    def test_separately_named_application_cannot_fall_through_to_ips(self):
        main = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(main.read_text(encoding="utf-8"))
        selection = next(node for node in tree.body
                         if isinstance(node, ast.If) and "_v1_handoff" in ast.unparse(node.test))
        env = {"_v1_handoff": None, "__name__": "v1_game_app",
               "I2C": lambda *_: self.fail("IPS I2C was unexpectedly called")}
        script = ast.Module(body=[selection], type_ignores=[])
        with self.assertRaisesRegex(RuntimeError, "explicit AMOLED V1 launcher"):
            exec(compile(script, str(main), "exec"), env)
