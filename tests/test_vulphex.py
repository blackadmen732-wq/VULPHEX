# VULPHEX: the 7 bots, one night each, on a synthetic market with a planted pattern (no internet, no model download).
import json, os, random, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "engine"))
import numpy as np
import bootcamp as bc
import brains
import vulphex


class VulphexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = bc.synthetic(S=80, T=900, plant=True); cls.F = brains.brain_inputs(cls.m)
        cls.syms = [f"S{i}" for i in range(80)]
        cls.bots = json.load(open(ROOT / "bots.json"))["bots"]

    def test_seven_bots_each_with_a_real_brain(self):
        self.assertEqual(len(self.bots), 7)
        self.assertEqual(len({b["name"] for b in self.bots}), 7)
        for b in self.bots:
            self.assertEqual(set(b["genome"]), set(brains.GENES))
            self.assertTrue(all(b["genome"][k] in brains.GENES[k] for k in brains.GENES), b["name"])
            self.assertIn(b["band"], ("popular", "ugly"))
        kinds = {b["genome"]["brain"] for b in self.bots}
        self.assertEqual(kinds, {"neuron", "forest", "rocket", "experts"})

    def test_challengers_keep_the_bots_kind_of_brain(self):
        g = self.bots[3]["genome"]; idea = {**g, "brain": "rocket", "hold": 10}
        cs = vulphex.challengers(g, [idea], random.Random(1))
        self.assertEqual(cs[0], g); self.assertTrue(all(c["brain"] == "experts" for c in cs)); self.assertEqual(len(cs), 4)

    def test_one_night_for_a_bot(self):
        bot = {"name": "T", "band": "ugly", "genome": {**self.bots[0]["genome"], "hold": 5, "inputs": "chart"}}
        asked = {}
        def coach(saved, genes):
            asked["saved"] = saved
            return [{**saved["genomes"][0], "pick": 0.2}], ["- AI coach (test model, $0): 1 ideas sent to the exams"]
        st, ledger = {}, {"tried": 0}
        lines = vulphex.run_bot(self.m, self.F, self.syms, bot, st, ledger, coach, seed=3)
        self.assertEqual(ledger["tried"], 4)                                   # the bot, 1 coach idea, 2 mutations
        self.assertEqual(asked["saved"]["genomes"][0], bot["genome"])
        self.assertEqual(st["genome"]["brain"], "neuron"); self.assertEqual(st["nights"], 1)
        self.assertIn("levels", lines[0]); self.assertTrue(any("paper desk" in l for l in lines))
        self.assertIn("open", st["desk"]); self.assertTrue(all(x["day"] == int(self.m.days[-1]) for x in st["desk"]["open"]))
        lines2 = vulphex.run_bot(self.m, self.F, self.syms, bot, st, ledger, coach, seed=4)  # second night: same day, no duplicate picks
        self.assertEqual(ledger["tried"], 8); self.assertEqual(st["nights"], 2)

    def test_luck_bar_rises_with_every_brain_tried(self):
        self.assertGreater(bc.required_z(400), bc.required_z(10))


if __name__ == "__main__":
    unittest.main()
