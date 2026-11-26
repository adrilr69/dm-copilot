"""Unit tests for the deterministic parts (no API key needed): dice, encounter rules, metrics,
chunking, tool validation. Run:  python -m pytest -q"""
import json

from src import tools
from src.chunking import fixed_windows, structure_chunks
from src.evaluate import mrr, ndcg_at_k, precision_at_k, recall_at_k
from src.retrieval import rrf_fuse


def test_dice_stats_fireball():
    s = json.loads(tools.dice_stats("8d6"))
    assert (s["min"], s["average"], s["max"]) == (8, 28.0, 48)


def test_dice_stats_with_modifier():
    s = json.loads(tools.dice_stats("2d6+4"))
    assert (s["min"], s["average"], s["max"]) == (6, 11.0, 16)


def test_multiattack_expression():
    s = json.loads(tools.dice_stats("3*(2d6+4)"))          # Troll: three Rend attacks
    assert (s["min"], s["average"], s["max"]) == (18, 33.0, 48)


def test_roll_is_reproducible_with_seed():
    a = json.loads(tools.roll_dice("4d6", seed=42))
    b = json.loads(tools.roll_dice("4d6", seed=42))
    assert a == b and 4 <= a["total"] <= 24


def test_advantage_average():
    s = json.loads(tools.dice_stats("2d20kh1"))
    assert abs(s["average"] - 13.82) < 0.01      # known value for advantage on a d20


def test_bad_dice_expression_is_an_error_observation():
    obs = tools.dispatch("roll_dice", '{"expression": "rm -rf"}')
    assert obs.startswith("Error")


# The three worked examples printed in SRD 5.2.1, p. 202-203
def test_encounter_example_1_low():
    r = json.loads(tools.encounter_difficulty([1, 1, 1, 1], [{"name": "Bugbear Warrior", "count": 1}]))
    assert r["budget"]["low"] == 200 and r["total_xp"] == 200 and r["difficulty"] == "LOW"


def test_encounter_example_2_moderate():
    r = json.loads(tools.encounter_difficulty([3] * 5, [{"name": "Druid", "count": 2},
                                                        {"name": "Stirge", "count": 9}]))
    assert r["budget"]["moderate"] == 1125 and r["total_xp"] == 1125 and r["difficulty"] == "MODERATE"


def test_encounter_example_3_high():
    r = json.loads(tools.encounter_difficulty([15] * 6, [{"name": "Adult Red Dragon", "count": 2},
                                                         {"name": "Fire Giant", "count": 2}]))
    assert r["budget"]["high"] == 46800 and r["total_xp"] == 46000 and r["difficulty"] == "HIGH"


def test_unknown_monster_is_reported_not_invented():
    r = json.loads(tools.encounter_difficulty([5, 5], [{"name": "Beholder", "count": 1}]))
    assert r["not_found"] == ["Beholder"] and r["total_xp"] == 0


def test_dispatch_never_crashes():
    assert tools.dispatch("serach_library", '{"query": "x"}').startswith("Error: unknown tool")
    assert tools.dispatch("dice_stats", "{}").startswith("Error: invalid arguments")
    assert tools.dispatch("dice_stats", "not json").startswith("Error")
    assert tools.classify_call("encounter_difficulty", '{"party_levels": "5"}') == "invalid"


def test_rrf_deck_case():
    assert rrf_fuse(["A", "B", "C"], ["B", "C", "d", "e", "f", "g", "h", "i", "A"])[:3] == ["B", "C", "A"]


def test_metrics_deck_case():
    ranked, gold = ["x", "g1", "g2", "x", "x"], ["g1", "g2"]
    assert recall_at_k(ranked, gold, 5) == 1.0
    assert precision_at_k(ranked, gold, 5) == 0.4
    assert mrr(ranked, gold) == 0.5
    assert abs(ndcg_at_k(ranked, gold, 5) - 0.69) < 0.005


def test_chunking():
    toy = " ".join(f"w{i}" for i in range(1000))
    assert len(fixed_windows(toy)) == 7
    statblock = "# Big Monster\nstats " + "x " * 200 + "\n## Actions\n" + "y " * 200
    chunks = structure_chunks(statblock, max_words=350)
    assert len(chunks) == 2 and chunks[1].startswith("## Actions")
