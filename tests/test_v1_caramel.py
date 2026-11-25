"""Drive the puppy's real touch-to-pose paths on the offline host V1 rig."""
from collections import defaultdict
from unittest import TestCase
from unittest.mock import patch

from ports import amoled_v1, v1_full_game_emulate as game


class CaramelV1Test(TestCase):
    def observe(self, frames, **kw):
        calls = defaultdict(list)
        original = game.runpy.run_path

        def watch(*args, **kwargs):
            ns = original(*args, **kwargs)
            art = ns["principal"].__globals__["d"]
            select = art._dog_pose

            def record(motion, eyes, mouth, sick):
                pose = select(motion, eyes, mouth, sick)
                if motion is not None:
                    calls[motion[0]].append((motion[1], eyes, mouth, pose))
                return pose

            art._dog_pose = record
            return ns

        with patch.object(game.runpy, "run_path", watch):
            image, result = game.emulate(
                frames, initial_pet="cachorro", fixtures={"cachorro": 45},
                screen_mode=amoled_v1.SCALE_LARGE, **kw,
            )
        self.assertEqual(image.size, (368, 448))
        self.assertEqual(result["pet"], "cachorro")
        self.assertEqual(result["life_stage"], "adulto")
        self.assertTrue(result["offline_forced"])
        self.assertEqual(result["saves"], "temporary")
        return calls, result

    def test_awake_tail_wags_and_real_feed_starts_chewing(self):
        seen, outcome = self.observe(
            game._idle(16) + (game._touch(48, 259),) + game._idle(16))
        awake = seen["idle"]
        chewing = seen["eating"]
        self.assertGreaterEqual(len(awake), 12)
        self.assertGreaterEqual(len(chewing), 12)
        self.assertGreaterEqual(len({p[3][:2] for p in awake}), 3)
        self.assertEqual({p[2] for p in chewing}, {"meia", "aberta"})
        # Chewing visibly alternates head nod and tongue; ordinary wag doesn't.
        self.assertEqual({pose[4] for _, _, _, pose in awake}, {0})
        self.assertEqual(len({pose[4] for _, _, _, pose in chewing}), 2)
        self.assertEqual({pose[6] for _, _, _, pose in chewing}, {False, True})
        self.assertEqual(outcome["saved_food"], {"cachorro": 70})
        self.assertEqual(outcome["fake_sound_events"].count("comer"), 1)

    def test_a_real_body_tap_wags_in_celebration(self):
        seen, outcome = self.observe(
            game._idle(8) + (game._touch(120, 166),) + game._idle(12))
        affectionate = seen["jump"] + seen["greeting"] + seen.get("happy", [])
        self.assertGreaterEqual(len(affectionate), 5)
        self.assertGreaterEqual(len({p[3] for p in affectionate}), 2)
        self.assertTrue({p[3] for p in affectionate} - {p[3] for p in seen["idle"]})
        self.assertEqual(outcome["fake_sound_events"].count("amor"), 1)
        self.assertEqual(outcome["saved_food"], {"cachorro": 45})

    def test_walk_in_each_direction_then_jump_with_the_short_touch(self):
        right, left = game._touch(205, 160), game._touch(40, 160)
        seen, outcome = self.observe(
            (right,) * 12 + game._idle(3) + (left,) * 12 + game._idle(3)
            + (right,) + game._idle(17), initial_mode="explore")
        for action, direction in (("walk-right", 1), ("walk-left", -1)):
            walk = seen[action]
            self.assertGreaterEqual(len(walk), 5)
            self.assertEqual({pose[5] for _, _, _, pose in walk}, {direction})
            self.assertGreaterEqual(len({pose[3] for _, _, _, pose in walk}), 2)
        self.assertGreaterEqual(len({p[3] for p in seen["jump"]}), 2)
        self.assertEqual(outcome["fake_sound_events"].count("pulo"), 1)

    def test_explore_uses_sleeping_pose_and_tail_stays_down(self):
        seen, outcome = self.observe(
            game._idle(12), initial_mode="explore",
            fixture_epoch=game._GameRig.epoch_start + 12 * 3600)
        asleep = seen["asleep"]
        self.assertGreaterEqual(len(asleep), 10)
        self.assertTrue(all(eyes == "fechados" and mouth == "dormindo"
                            for _, eyes, mouth, _ in asleep))
        poses = {p[3] for p in asleep}
        self.assertEqual(len(poses), 1)
        lowered_tail = next(iter(poses))
        self.assertGreater(lowered_tail[1], -20)
        self.assertFalse(lowered_tail[6])
        self.assertNotIn("pulo", outcome["fake_sound_events"])
