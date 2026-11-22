import contextlib
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from zoo.pip import replay


class PipReplayTest(unittest.TestCase):
    def test_default_story_is_repeatable_and_checks_resumed_future(self):
        first = replay.replay()
        self.assertEqual(first, replay.replay())
        steps = first["steps"]
        self.assertEqual([x["event"] for x in steps if "event" in x],
                         ["feed", "stroke", "sleep", "wake"])
        self.assertEqual(steps[1]["reaction_reason"], "fed_while_full")
        self.assertTrue(steps[3]["state"]["asleep"])
        self.assertEqual(steps[4]["roundtrip"], "identical")
        self.assertTrue(steps[5]["state"]["asleep"])
        self.assertGreaterEqual(steps[5]["elapsed_s"] - steps[4]["elapsed_s"], 10 * 3600)
        self.assertFalse(steps[6]["state"]["asleep"])
        self.assertEqual(first["checkpoints"], 1)
        self.assertEqual(first["verified_steps"], 3)
        self.assertTrue(all(isinstance(x["state"]["reason"]["kind"], str) for x in steps))

    def test_bad_step_never_enters_engine(self):
        examples = (
            [],
            [{"op": "observe", "after_s": -1}],
            [{"op": "observe", "after_s": True}],
            [{"op": "observe", "after_s": 32 * 86400}],
            [{"op": "observe", "after_s": 1, "path": "brain.bin"}],
            [{"op": "event", "name": "unknown", "after_s": 0}],
            [{"op": "event", "after_s": 0}],
        )
        for steps in examples:
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                replay.replay(steps)
        canonical = replay.validate_steps([{"op": "event", "name": "fed-up", "after_s": 0}])
        self.assertEqual(canonical[0]["name"], "fed_up")

    def test_cli_accepts_json_script_and_only_reads_its_directory(self):
        steps = [{"op": "event", "name": "feed", "after_s": 1},
                 {"op": "checkpoint", "after_s": 2},
                 {"op": "observe", "after_s": 3}]
        with TemporaryDirectory() as folder:
            path = Path(folder) / "the-story.json"
            path.write_text(json.dumps(steps), encoding="utf-8")
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                self.assertEqual(replay.main(["--json", "--scenario", str(path), "--seed", "7"]), 0)
            output = json.loads(stream.getvalue())
            self.assertEqual(output["seed"], 7)
            self.assertEqual(output["verified_steps"], 1)
            self.assertEqual([x["elapsed_s"] for x in output["steps"]], [1, 3, 6])
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_human_output_names_checkpoint_and_pet_actions(self):
        text = replay._human(replay.replay())
        self.assertIn("покормить", text)
        self.assertIn("Пип уже был сыт", text)
        self.assertIn("сытость=90%", text)
        self.assertIn("сохранение → загрузка: совпало", text)
        self.assertIn("совпавших следующих шагов: 3", text)


if __name__ == "__main__":
    unittest.main()
