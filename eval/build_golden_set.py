"""Builds eval/golden_set.jsonl — the hand-labelled golden set.

Each question has:
- gold:      the document ids that answer it (doc-level, so the 3 chunking strategies are comparable).
             For generic questions, both official versions (SRD 5.2 = srd-2024_*, SRD 5.1 = srd_*) are gold.
- expected:  for the agent — a list of groups; each group lists acceptable strings, ALL groups must appear.
- answerable=False: out-of-library traps (product-identity monsters absent from the open SRD/OGL corpus).
- split:     'dev' (used while tuning) or 'test' (held out, reported).
Run:  python eval/build_golden_set.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
T, D = "test", "dev"

Q = [
    # --- exact names: the lexical case (BM25 should shine) ------------------------------------
    ("name01", "exact_name", T, "How many hit points does a Troll have in the 2024 rules?",
     ["srd-2024_troll", "srd_troll"], [["94"]]),
    ("name02", "exact_name", T, "How much damage does the Fireball spell deal?",
     ["srd-2024_fireball", "srd_fireball"], [["8d6"]]),
    ("name03", "exact_name", D, "How much weight can a Bag of Holding carry?",
     ["srd-2024_bag-of-holding", "srd_bag-of-holding"], [["500"]]),
    ("name04", "exact_name", T, "How many experience points is an Owlbear worth?",
     ["srd-2024_owlbear", "srd_owlbear"], [["700"]]),
    ("name05", "exact_name", T, "What is the casting time of Counterspell?",
     ["srd-2024_counterspell", "srd_counterspell"], [["reaction"]]),
    ("name06", "exact_name", D, "What is the challenge rating of a Lich?",
     ["srd-2024_lich", "srd_lich"], [["21"]]),
    ("name07", "exact_name", T, "What is the Armor Class of the Tarrasque?",
     ["srd-2024_tarrasque", "srd_tarrasque"], [["25"]]),
    ("name08", "exact_name", T, "How far can you teleport with Misty Step?",
     ["srd-2024_misty-step", "srd_misty-step"], [["30"]]),
    ("name09", "exact_name", D, "What does the Mimic's Adhesive trait do?",
     ["srd-2024_mimic", "srd_mimic"], [["adher", "stuck", "stick", "grappl", "colle"]]),
    ("name10", "exact_name", T, "How deep is a Portable Hole?",
     ["srd-2024_portable-hole", "srd_portable-hole"], [["10"]]),
    ("name11", "exact_name", T, "What material component does Revivify require and how much is it worth?",
     ["srd-2024_revivify", "srd_revivify"], [["diamond", "diamant"], ["300"]]),
    ("name12", "exact_name", D, "How long does Water Breathing last?",
     ["srd-2024_water-breathing", "srd_water-breathing"], [["24"]]),
    # --- paraphrases: no exact name, the semantic case (dense should shine) ----------------------
    ("para01", "paraphrase", T, "Which large giant regrows lost limbs and only stops regenerating after fire or acid damage?",
     ["srd-2024_troll", "srd_troll"], [["troll"]]),
    ("para02", "paraphrase", T, "Is there a spell that lets my whole party breathe underwater for a day?",
     ["srd-2024_water-breathing", "srd_water-breathing"], [["water breathing", "respiration aquatique"]]),
    ("para03", "paraphrase", D, "A magic sack that is much bigger on the inside than on the outside",
     ["srd-2024_bag-of-holding", "srd_bag-of-holding", "srd-2024_handy-haversack", "srd_handy-haversack"],
     [["bag of holding", "haversack", "sac sans fond"]]),
    ("para04", "paraphrase", T, "A transparent cube of acidic ooze that fills dungeon corridors and engulfs adventurers",
     ["srd-2024_gelatinous-cube", "srd_gelatinous-cube"], [["gelatinous cube", "cube gélatineux"]]),
    ("para05", "paraphrase", T, "A monster that disguises itself as a treasure chest or a door to ambush adventurers",
     ["srd-2024_mimic", "srd_mimic"], [["mimic"]]),
    ("para06", "paraphrase", D, "Spell that teleports you a short distance as a bonus action in a puff of silvery mist",
     ["srd-2024_misty-step", "srd_misty-step"], [["misty step", "foulée brumeuse"]]),
    ("para07", "paraphrase", T, "An undead spellcaster that hides its soul in a phylactery to become immortal",
     ["srd-2024_lich", "srd_lich"], [["lich", "liche"]]),
    ("para08", "paraphrase", T, "A reaction spell to interrupt and cancel another creature's spell",
     ["srd-2024_counterspell", "srd_counterspell"], [["counterspell", "contresort"]]),
    ("para09", "paraphrase", D, "A potion that gives you a flying speed for an hour",
     ["srd-2024_potion-of-flying", "srd_potion-of-flying"], [["potion of flying", "vol"]]),
    ("para10", "paraphrase", T, "The colossal, nearly unkillable monster that sleeps for ages and devastates whole regions",
     ["srd-2024_tarrasque", "srd_tarrasque"], [["tarrasque"]]),
    # --- rules ------------------------------------------------------------------------------------
    ("rule01", "rules", T, "What is an opportunity attack and what does it cost?",
     ["srd_attacking_opportunity-attacks", "srd-2024_combat_melee-attacks"], [["reaction"]]),
    ("rule02", "rules", T, "How much does half cover and three-quarters cover add to Armor Class?",
     ["srd-2024_combat_cover"], [["+2", "2 bonus", "bonus of 2"], ["+5", "5 bonus", "bonus of 5"]]),
    ("rule03", "rules", D, "What happens to a creature that has the Grappled condition?",
     ["grappled"], [["speed"]]),
    ("rule04", "rules", T, "What does the Poisoned condition do?",
     ["poisoned"], [["disadvantage", "désavantage"]]),
    ("rule05", "rules", T, "How do death saving throws work when a character drops to 0 hit points?",
     ["srd-2024_damage-and-healing_dropping-to-zero-hit-points"], [["three", "3", "trois"]]),
    ("rule06", "rules", D, "How long does a long rest last and what does it restore?",
     ["srd-2024_damage-and-healing_resting"], [["8"]]),
    ("rule07", "rules", T, "What is the XP budget per character for a moderate encounter at character level 5?",
     ["srd52pdf_srd52_combat_encounters"], [["750"]]),
    ("rule08", "rules", T, "What ability score do I need to multiclass into another class?",
     ["srd-2024_multiclassing_prerequisties", "srd_multiclassing_prerequistes"], [["13"]]),
    ("rule09", "rules", D, "What does the Exhaustion condition do?",
     ["exhaustion"], [["exhaustion", "épuisement"]]),
    # --- open extensions (third-party books) ----------------------------------------------------
    ("ext01", "extension", T, "What is a Dullahan in the Tome of Beasts?",
     ["tob-2023_dullahan"], [["fey", "fée", "headless", "sans tête"]]),
    ("ext02", "extension", T, "Is there a magic teapot that calms people down?",
     ["vom_teapot-of-soothing"], [["teapot", "théière"]]),
    ("ext03", "extension", D, "What is the Way of the Tipsy Monkey monk tradition?",
     ["toh_way-of-the-tipsy-monkey"], [["monk", "moine"]]),
    ("ext04", "extension", T, "What is the Runechild sorcerer from the Tal'Dorei Campaign Setting?",
     ["tdcs_runechild"], [["sorcerer", "ensorceleur"]]),
    ("ext05", "extension", T, "What does the spell Hedren's Birds of Clay do?",
     ["deepm_hedrens-birds-of-clay"], [["clay", "argile"]]),
    ("ext06", "extension", D, "What is an Ahuizotl?",
     ["ccdx_ahuizotl"], [["monstrosity", "monstruosité", "swim", "nage"]]),
    ("ext07", "extension", T, "Stats of the Cave Giant Shaman from Tome of Beasts 2",
     ["tob2_cave-giant-shaman"], [["207"]]),
    # --- comparisons (several gold documents) ---------------------------------------------------
    ("cmp01", "comparison", T, "Compare the challenge ratings of the Adult Red Dragon and the Adult Blue Dragon",
     ["srd-2024_adult-red-dragon", "srd-2024_adult-blue-dragon", "srd_adult-red-dragon", "srd_adult-blue-dragon"],
     [["17"], ["16"]]),
    ("cmp02", "comparison", T, "In the 2024 rules, how many dice of healing do Cure Wounds and Healing Word restore?",
     ["srd-2024_cure-wounds", "srd-2024_healing-word"], [["2d8"], ["2d4"]]),
    ("cmp03", "comparison", D, "Which has more hit points, a Fire Giant or a Frost Giant?",
     ["srd-2024_fire-giant", "srd-2024_frost-giant", "srd_fire-giant", "srd_frost-giant"],
     [["fire giant", "géant du feu"]]),
    # --- multi-step: the agent must combine retrieval + tools -----------------------------------
    ("agent01", "multi_step", T, "How difficult is an encounter with 2 Trolls for a party of four level 5 characters?",
     ["srd-2024_troll"], [["high", "élevée", "elevee", "difficile"]]),
    ("agent02", "multi_step", T, "Four level 3 characters fight 1 Owlbear and 2 Wolves. What is the encounter difficulty?",
     ["srd-2024_owlbear", "srd-2024_wolf"], [["moderate", "modérée", "moderee"]]),
    ("agent03", "multi_step", T, "Is one Ogre a fair fight for four level 1 characters?",
     ["srd-2024_ogre"], [["beyond", "deadly", "mortel", "au-delà", "au-dela", "lethal", "létal"]]),
    ("agent04", "multi_step", T, "What is the average damage of a Fireball cast with a 5th-level spell slot?",
     ["srd-2024_fireball"], [["35"]]),
    ("agent05", "multi_step", D, "What is the average damage of one Rend attack from a Troll (2024)?",
     ["srd-2024_troll"], [["11"]]),
    ("agent06", "multi_step", T, "Six level 15 characters face 2 Adult Red Dragons and 2 Fire Giants. How hard is it?",
     ["srd-2024_adult-red-dragon", "srd-2024_fire-giant"], [["high", "élevée", "elevee"]]),
    ("agent07", "multi_step", T, "Combien de points de vie a un Troll selon les règles 2024 ?",
     ["srd-2024_troll"], [["94"]]),
    ("agent08", "multi_step", T, "Mes 5 joueurs de niveau 3 affrontent 2 druides et 9 stirges : quelle est la difficulté de la rencontre ?",
     ["srd-2024_druid", "srd-2024_stirge"], [["moderate", "modérée", "moderee", "modéré"]]),
    ("agent09", "multi_step", D, "Quelle est la classe d'armure de la Tarrasque ?",
     ["srd-2024_tarrasque"], [["25"]]),
    # --- out-of-library traps: product-identity monsters NOT in the open SRD/OGL content ---------
    ("trap01", "out_of_library", T, "What are the stats of a Beholder?", [], None),
    ("trap02", "out_of_library", T, "What is the challenge rating of a Mind Flayer?", [], None),
    ("trap03", "out_of_library", D, "What is the Armor Class of a Displacer Beast?", [], None),
    ("trap04", "out_of_library", T, "Quelles sont les statistiques de Strahd von Zarovich ?", [], None),
    ("trap05", "out_of_library", T, "How strong is a Githyanki Knight?", [], None),
    ("trap06", "out_of_library", D, "What does the Umber Hulk's confusing gaze do?", [], None),
]


def main():
    docs = {json.loads(l)["doc_id"] for l in (HERE.parent / "data/processed/documents.jsonl").open(encoding="utf-8")}
    rows = []
    for qid, cat, split, q, gold, expected in Q:
        unknown = [g for g in gold if g not in docs]
        assert not unknown, f"{qid}: unknown gold ids {unknown}"
        rows.append({"id": qid, "category": cat, "split": split, "question": q, "gold": gold,
                     "expected": expected or [], "answerable": expected is not None, "agent": True})
    (HERE / "golden_set.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                                           encoding="utf-8")
    n_test = sum(r["split"] == "test" for r in rows)
    print(f"{len(rows)} questions ({n_test} test / {len(rows) - n_test} dev) -> eval/golden_set.jsonl")


if __name__ == "__main__":
    main()
