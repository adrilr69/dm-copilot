"""Step 2 — turn the raw Open5e JSON into clean, citable documents.

One document = one game entry (a monster, a spell, a magic item, a rules section, a class...).
Each document is rendered as readable Markdown (what the LLM and the user will see) and keeps
its metadata (type, source book, edition, CR, spell level...) for filtering and citations.

Run:  python -m src.ingest      ->  data/processed/documents.jsonl
"""
import json
import re
from collections import Counter

from src.config import DATA_RAW, DOCS_PATH, ROOT

EXTRA_DIR = ROOT / "data" / "extra"

# Books we skip: image-only packs, and older printings superseded by a newer edition
# already in the corpus (avoids near-duplicate documents that would split the retrieval votes).
SKIP_DOCUMENTS = {"elderberry-inn-icons", "tob"}   # tob is superseded by tob-2023
OFFICIAL = {"srd-2014", "srd-2024"}

ABILITIES = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]
ACTION_SECTIONS = [("ACTION", "Actions"), ("BONUS_ACTION", "Bonus Actions"),
                   ("REACTION", "Reactions"), ("LEGENDARY_ACTION", "Legendary Actions")]


def clean(text) -> str:
    if not text:
        return ""
    text = str(text).replace("\r", "").replace("�", "-")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def fmt_cr(cr) -> str:
    if cr is None:
        return "?"
    return {0.125: "1/8", 0.25: "1/4", 0.5: "1/2"}.get(float(cr), str(int(cr)) if float(cr).is_integer() else str(cr))


def doc_info(doc) -> dict:
    """Normalise the `document` field (sometimes a dict, sometimes a key)."""
    if isinstance(doc, dict):
        gs = doc.get("gamesystem") or {}
        return {"source_key": doc.get("key"), "source": doc.get("name"),
                "publisher": (doc.get("publisher") or {}).get("name"),
                "edition": gs.get("key") if isinstance(gs, dict) else gs,
                "permalink": doc.get("permalink")}
    return {"source_key": doc, "source": doc, "publisher": None, "edition": None, "permalink": None}


def header(name: str, subtitle: str, info: dict) -> str:
    return f"# {name}\n*{subtitle}* — Source: {info['source']}"


# ----------------------------------------------------------------------------- renderers
def render_creature(r, info):
    size = (r.get("size") or {}).get("name", "")
    ctype = (r.get("type") or {}).get("name", "")
    sub = f"{size} {ctype}, {r.get('alignment') or 'unaligned'}".strip()
    speed = r.get("speed") or {}
    unit = speed.get("unit", "feet")
    speed_txt = ", ".join(f"{k} {v} ft." for k, v in speed.items()
                          if k not in ("unit", "hover") and v) or "?"
    scores = r.get("ability_scores") or {}
    mods = r.get("modifiers") or {}
    abil = " | ".join(f"{a[:3].upper()} {scores.get(a, '?')} ({mods.get(a, 0):+d})"
                      if isinstance(mods.get(a), int) else f"{a[:3].upper()} {scores.get(a, '?')}"
                      for a in ABILITIES)
    lines = [header(r["name"], sub, info),
             f"**Armor Class** {r.get('armor_class')}"
             + (f" ({r['armor_detail']})" if r.get("armor_detail") else "")
             + f" · **Hit Points** {r.get('hit_points')}"
             + (f" ({r['hit_dice']})" if r.get("hit_dice") else "")
             + f" · **Speed** {speed_txt}",
             abil]
    saves = r.get("saving_throws") or {}
    if saves:
        lines.append("**Saving Throws** " + ", ".join(f"{k[:3].title()} {v:+d}" for k, v in saves.items()
                                                       if isinstance(v, int)))
    skills = r.get("skill_bonuses") or {}
    if skills:
        lines.append("**Skills** " + ", ".join(f"{k.replace('_', ' ').title()} {v:+d}"
                                                for k, v in skills.items() if isinstance(v, int)))
    ri = r.get("resistances_and_immunities") or {}
    for label, key in [("Damage Vulnerabilities", "damage_vulnerabilities_display"),
                       ("Damage Resistances", "damage_resistances_display"),
                       ("Damage Immunities", "damage_immunities_display"),
                       ("Condition Immunities", "condition_immunities_display")]:
        if ri.get(key):
            lines.append(f"**{label}** {ri[key]}")
    senses = [f"{s} {r[f'{s}_range']} ft." for s in ("darkvision", "blindsight", "tremorsense", "truesight")
              if r.get(f"{s}_range")]
    senses.append(f"passive Perception {r.get('passive_perception')}")
    lines.append("**Senses** " + ", ".join(senses))
    langs = (r.get("languages") or {}).get("as_string")
    if langs:
        lines.append(f"**Languages** {langs}")
    xp = r.get("experience_points")
    lines.append(f"**Challenge** {fmt_cr(r.get('challenge_rating'))}"
                 + (f" ({xp:,} XP)" if isinstance(xp, int) else ""))
    if r.get("desc"):
        lines.append("\n" + clean(r["desc"]))
    if r.get("traits"):
        lines.append("\n## Traits")
        lines += [f"**{t['name']}.** {clean(t.get('desc'))}" for t in r["traits"]]
    actions = sorted(r.get("actions") or [], key=lambda a: a.get("order_in_statblock") or 0)
    for code, title in ACTION_SECTIONS:
        block = [a for a in actions if (a.get("action_type") or "ACTION") == code]
        if block:
            lines.append(f"\n## {title}")
            lines += [f"**{a['name']}.** {clean(a.get('desc'))}" for a in block]
    meta = {"cr": r.get("challenge_rating"), "xp": xp, "creature_type": ctype, "size": size,
            "hp": r.get("hit_points"), "ac": r.get("armor_class")}
    return "\n".join(lines), meta


def render_spell(r, info):
    lvl = r.get("level", 0)
    school = (r.get("school") or {}).get("name", "")
    sub = f"{school} cantrip" if lvl == 0 else f"Level {lvl} {school}"
    if r.get("ritual"):
        sub += " (ritual)"
    comps = [c for c, k in (("V", "verbal"), ("S", "somatic"), ("M", "material")) if r.get(k)]
    comp_txt = ", ".join(comps) + (f" ({r['material_specified']})" if r.get("material_specified") else "")
    dur = r.get("duration") or "?"
    if r.get("concentration"):
        dur = f"Concentration, {dur}"
    classes = ", ".join(c["name"] for c in (r.get("classes") or []))
    lines = [header(r["name"], sub, info),
             f"**Casting Time** {r.get('casting_time')} · **Range** {r.get('range_text') or r.get('range')}"
             f" · **Components** {comp_txt} · **Duration** {dur}"]
    if classes:
        lines.append(f"**Classes** {classes}")
    lines.append("\n" + clean(r.get("desc")))
    if r.get("higher_level"):
        lines.append(f"\n**At Higher Levels.** {clean(r['higher_level'])}")
    meta = {"level": lvl, "school": school, "classes": classes,
            "damage_roll": r.get("damage_roll"), "concentration": bool(r.get("concentration"))}
    return "\n".join(lines), meta


def render_magicitem(r, info):
    cat = (r.get("category") or {}).get("name", "Item")
    rarity = (r.get("rarity") or {}).get("name", "")
    sub = f"{cat}, {rarity}".strip(", ")
    if r.get("requires_attunement"):
        sub += " (requires attunement" + (f" {r['attunement_detail']}" if r.get("attunement_detail") else "") + ")"
    text = header(r["name"], sub, info) + "\n\n" + clean(r.get("desc"))
    return text, {"rarity": rarity, "category": cat, "attunement": bool(r.get("requires_attunement"))}


def render_item(r, info):
    cat = r.get("category") or "Equipment"
    cat = cat.get("name", "Equipment") if isinstance(cat, dict) else str(cat).title()
    bits = []
    if r.get("cost") not in (None, "0.00"):
        bits.append(f"**Cost** {r['cost']} gp")
    if r.get("weight") not in (None, "0.000"):
        bits.append(f"**Weight** {r['weight']} {r.get('weight_unit') or 'lb'}")
    for k in ("damage_dice", "damage_type", "ac_display", "range", "long_range"):
        v = r.get(k)
        if isinstance(v, dict):
            v = v.get("name")
        if v:
            bits.append(f"**{k.replace('_', ' ').title()}** {v}")
    props = r.get("properties") or []
    if props:
        names = [(p.get("property") or {}).get("name") if isinstance(p, dict) else str(p) for p in props]
        bits.append("**Properties** " + ", ".join(n for n in names if n))
    text = header(r["name"], cat, info) + ("\n" + " · ".join(bits) if bits else "")
    if r.get("desc"):
        text += "\n\n" + clean(r["desc"])
    return text, {"category": cat}


def render_rule(r, info, rulesets):
    rs = rulesets.get(r.get("ruleset"), {})
    chapter = rs.get("name") or (r.get("ruleset") or "Rules")
    text = header(r["name"], f"Rules — {chapter}", info) + "\n\n" + clean(r.get("desc"))
    return text, {"chapter": chapter}


EDITION_LABEL = {"srd-2024": "SRD 5.2 (2024 rules)", "srd-2014": "SRD 5.1 (2014 rules)",
                 "a5e-ag": "Level Up A5E (Adventurer's Guide)"}


def render_condition(r, info):
    descs = r.get("descriptions") or []
    body = "\n\n".join(f"**{EDITION_LABEL.get(d.get('document'), d.get('document'))}.** {clean(d.get('desc'))}"
                       for d in descs) or clean(r.get("desc"))
    return header(r["name"], "Condition", info) + "\n\n" + body, {}


def render_class(r, info):
    sub = "Subclass" + (f" of {r['subclass_of']['name']}" if isinstance(r.get("subclass_of"), dict) else "") \
        if r.get("subclass_of") else "Class"
    lines = [header(r["name"], sub, info)]
    if r.get("hit_dice"):
        lines.append(f"**Hit Die** {r['hit_dice']}"
                     + (f" · **Primary abilities** {', '.join(a['name'] if isinstance(a, dict) else str(a) for a in r['primary_abilities'])}"
                        if r.get("primary_abilities") else ""))
    if r.get("desc"):
        lines.append("\n" + clean(r["desc"]))
    feats = r.get("features") or []

    def first_level(f):
        lv = [g.get("level") for g in (f.get("gained_at") or []) if g.get("level")]
        return min(lv) if lv else 0
    for f in sorted(feats, key=first_level):
        lv = first_level(f)
        lines.append(f"\n## {f['name']}" + (f" (level {lv})" if lv else ""))
        lines.append(clean(f.get("desc")))
    return "\n".join(lines), {}


def render_named_list(r, info, label, key):
    lines = [header(r["name"], label, info)]
    if r.get("prerequisite"):
        lines.append(f"**Prerequisite** {r['prerequisite']}")
    if r.get("desc"):
        lines.append("\n" + clean(r["desc"]))
    for b in r.get(key) or []:
        name = b.get("name")
        lines.append((f"**{name}.** " if name else "- ") + clean(b.get("desc")))
    return "\n".join(lines), {}


# ----------------------------------------------------------------------------- main
def load(name):
    p = DATA_RAW / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def build_documents():
    licenses = {d["key"]: [l.get("name") for l in (d.get("licenses") or []) if isinstance(l, dict)]
                for d in load("documents")}
    rulesets = {r["key"]: r for r in load("rulesets")}
    specs = [
        ("creatures", "creature", render_creature),
        ("spells", "spell", render_spell),
        ("magicitems", "magic_item", render_magicitem),
        ("items", "equipment", render_item),
        ("weapons", "equipment", render_item),
        ("armor", "equipment", render_item),
        ("rules", "rule", lambda r, i: render_rule(r, i, rulesets)),
        ("conditions", "condition", render_condition),
        ("classes", "class", render_class),
        ("species", "species", lambda r, i: render_named_list(r, i, "Species", "traits")),
        ("feats", "feat", lambda r, i: render_named_list(r, i, f"Feat ({r.get('type') or 'General'})", "benefits")),
        ("backgrounds", "background", lambda r, i: render_named_list(r, i, "Background", "benefits")),
    ]
    docs, seen = [], set()
    for endpoint, dtype, render in specs:
        for r in load(endpoint):
            info = doc_info(r.get("document") or (r.get("key", "").split("_")[0]))
            if info["source_key"] in SKIP_DOCUMENTS or r["key"] in seen:
                continue
            if info["source"] == info["source_key"] and endpoint == "rules":
                info["source"] = {"srd-2024": "System Reference Document 5.2",
                                  "srd-2014": "System Reference Document 5.1"}.get(info["source_key"], info["source_key"])
            text, meta = render(r, info)
            if len(text.split()) < 12:          # empty stubs carry no knowledge
                continue
            seen.add(r["key"])
            docs.append({
                "doc_id": r["key"], "type": dtype, "name": r["name"],
                "source_key": info["source_key"], "source": info["source"],
                "publisher": info["publisher"], "edition": info["edition"],
                "tier": "official" if info["source_key"] in OFFICIAL else "extension",
                "license": " / ".join(licenses.get(info["source_key"], [])),
                "illustration": (r.get("illustration") or {}).get("file_url") if isinstance(r.get("illustration"), dict) else None,
                "meta": meta, "text": text,
            })
    # Extra rule sections extracted by hand from the official SRD 5.2.1 PDF (CC BY 4.0),
    # for rules Open5e does not expose (e.g. the encounter-building XP budget table).
    for p in sorted(EXTRA_DIR.glob("*.md")):
        text = p.read_text(encoding="utf-8").strip()
        name = text.splitlines()[0].lstrip("# ").strip()
        docs.append({"doc_id": f"srd52pdf_{p.stem}", "type": "rule", "name": name,
                     "source_key": "srd-2024", "source": "System Reference Document 5.2.1 (PDF)",
                     "publisher": "Wizards of the Coast", "edition": "5e-2024", "tier": "official",
                     "license": "Creative Commons Attribution 4.0", "illustration": None,
                     "meta": {"chapter": "Gameplay Toolbox"}, "text": text})
    return docs


def main():
    docs = build_documents()
    with DOCS_PATH.open("w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    words = sum(len(d["text"].split()) for d in docs)
    print(f"{len(docs)} documents, {words:,} words -> {DOCS_PATH}")
    print("by type:  ", dict(Counter(d["type"] for d in docs).most_common()))
    print("by source:", dict(Counter(d["source_key"] for d in docs).most_common()))
    print("by tier:  ", dict(Counter(d["tier"] for d in docs)))


if __name__ == "__main__":
    main()
