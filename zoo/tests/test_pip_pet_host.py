"""Integration checks against the unmodified original C decision tree."""
import unittest

from zoo.pip.pet_host import Pet


class PipPetHostTests(unittest.TestCase):
    def test_full_pip_reacts_to_repeated_feeding(self):
        p = Pet(seed=11, now=1795377600)
        self.assertEqual(p.event("feed"), "nauseous")
        self.assertEqual(p.event("feed"), "disgusted")
        self.assertEqual(p.explain()["needs"]["food"], 1.0)

    def test_explain_win_and_expiry_on_same_clock(self):
        p = Pet(seed=11, now=1795377600)
        self.assertEqual(p.event("win"), "smug")
        why = p.explain()["reason"]
        self.assertEqual((why["kind"], why["detail"]), ("after", "win"))
        self.assertGreater(why["value"], 0)
        self.assertNotEqual(p.update(1795377900)["reason"]["detail"], "win")
        with self.assertRaises(ValueError):
            p.update(1795377800)

    def test_corrupt_native_snapshot_rejected(self):
        p = Pet(seed=11, now=1795377600)
        blob = p.snapshot()
        self.assertEqual(Pet.restore(blob).explain(), p.explain())
        bad = blob[:-1] + bytes((blob[-1] ^ 1,))
        with self.assertRaisesRegex(ValueError, "CRC"):
            Pet.restore(bad)
