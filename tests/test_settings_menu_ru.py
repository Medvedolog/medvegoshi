"""Exercise firmware menu hit targets without importing any board driver."""
import ast
from pathlib import Path
import unittest


def load_menu():
    path = Path(__file__).resolve().parents[1] / "desenho.py"
    ast_tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {"MENU_FUNDO", "MODOS", "AJUSTES_ROT", "AJUSTES_MIN",
             "MENU_CLOCK_X", "MENU_CLOCK_STEP", "MENU_CLOCK_W",
             "MENU_MODE_X", "MENU_MODE_STEP", "MENU_MODE_W", "MENU_MODE_Y", "MENU_MODE_H"}
    nodes = [node for node in ast_tree.body if
             (isinstance(node, ast.FunctionDef) and node.name == "menu_toque") or
             (isinstance(node, ast.Assign) and any(
                 isinstance(ref, ast.Name) and ref.id in names
                 for target in node.targets for ref in ast.walk(target)))]
    env = {"W": 240}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), env)
    return env


class RussianSettingsMenu(unittest.TestCase):
    def test_clock_units_are_russian_and_each_label_matches_the_touch(self):
        env = load_menu()
        self.assertEqual(env["AJUSTES_ROT"], ("-1 мин", "-1 ч", "+1 ч", "+1 мин"))
        hit = env["menu_toque"]
        for idx, value in enumerate((-1, -60, 60, 1)):
            left = env["MENU_CLOCK_X"] + idx * env["MENU_CLOCK_STEP"]
            self.assertEqual(hit(left, 214, "real"), ("ajuste", value))
            self.assertEqual(hit(left + env["MENU_CLOCK_W"] - 1, 235, "real"),
                             ("ajuste", value))
            self.assertIsNone(hit(left + env["MENU_CLOCK_W"], 235, "real"))

    def test_mode_buttons_match_painted_areas_and_leave_gaps_in_both_views(self):
        from ports.v1_scale import VIEWPORT_LARGE, VIEWPORT_NATIVE

        env = load_menu()
        self.assertEqual(env["MODOS"], (("pet", "Забота"), ("companion", "Сам"),
                                       ("explore", "Гуляшки")))
        y, h = env["MENU_MODE_Y"], env["MENU_MODE_H"]
        width = env["MENU_MODE_W"]
        hit = env["menu_toque"]
        for index, (mode, _) in enumerate(env["MODOS"]):
            left = env["MENU_MODE_X"] + index * env["MENU_MODE_STEP"]
            for view in (VIEWPORT_NATIVE, VIEWPORT_LARGE):
                for x, yy in ((left, y), (left + width // 2, y + h // 2),
                              (left + width - 1, y + h - 1)):
                    panel_point = view.logical_to_physical(x, yy)
                    logical = view.physical_to_logical(*panel_point)
                    self.assertEqual(hit(*logical, "real"), ("modo", mode))
                gap = view.logical_to_physical(left + width, y + h // 2)
                self.assertIsNone(hit(*view.physical_to_logical(*gap), "real"))

    def test_switch_reset_and_cancel_use_separate_controls(self):
        hit = load_menu()["menu_toque"]
        self.assertEqual(hit(168, 78, "real"), ("personagem", 1))
        self.assertEqual(hit(24, 220, "real", "trocar"), ("sim", None))
        self.assertEqual(hit(196, 220, "real", "trocar"), ("nao", None))
        self.assertIsNone(hit(120, 220, "real", "trocar"))
        self.assertEqual(hit(40, 252, "real"), ("zerar", None))
        self.assertEqual(hit(195, 252, "real"), ("som", None))
        self.assertEqual(hit(120, 252, "real"), ("fechar", None))
