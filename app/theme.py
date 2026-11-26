"""D&D look & feel: parchment, stat-block cards, Cinzel titles. Pure CSS + small HTML helpers."""
import html
import re

TYPE_ICON = {"creature": "🐉", "spell": "✨", "magic_item": "💎", "rule": "📜", "condition": "🌀",
             "class": "⚔️", "species": "🧝", "feat": "🏅", "background": "🎭", "equipment": "🛡️"}
TOOL_ICON = {"search_library": "🔍", "get_entry": "📖", "roll_dice": "🎲", "dice_stats": "📊",
             "encounter_difficulty": "⚔️", "final_answer": "🪶"}
TOOL_LABEL = {"search_library": "Searches the library", "get_entry": "Opens a tome",
              "roll_dice": "Rolls the dice", "dice_stats": "Computes the odds",
              "encounter_difficulty": "Weighs the encounter", "final_answer": "Writes the answer"}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700;900&family=Crimson+Text:ital,wght@0,400;0,600;1,400&display=swap');

html, body, [class*="css"], .stMarkdown, p, li, label, .stTextInput input, .stTextArea textarea {
  font-family: 'Crimson Text', Georgia, serif !important; font-size: 1.05rem;
}
.stApp {
  background:
    radial-gradient(ellipse at top left, rgba(255,250,235,.85), transparent 60%),
    radial-gradient(ellipse at bottom right, rgba(160,110,50,.18), transparent 55%),
    linear-gradient(180deg, #F6EBD2 0%, #EEDDB8 100%);
}
h1, h2, h3, h4, .cinzel { font-family: 'Cinzel', serif !important; color: #58180D !important; letter-spacing: .5px; }
section[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #3B1F12 0%, #22120A 100%);
  border-right: 3px solid #C9A34E;
}
section[data-testid="stSidebar"] * { color: #F3E6C9 !important; }
section[data-testid="stSidebar"] .stRadio label p { font-family: 'Cinzel', serif !important; font-size: 1.02rem; }

.hero {
  text-align: center; padding: 18px 10px 8px 10px; margin-bottom: 8px;
  border-bottom: 3px double #922610;
}
.hero h1 { font-size: 2.6rem; margin: 0; color: #58180D !important; text-shadow: 1px 1px 0 #E4C98F; }
.hero p { margin: 4px 0 0 0; font-style: italic; color: #5A3B22; font-size: 1.15rem; }

/* Stat block card (5e style) */
.statblock {
  background: #FDF1DC; border-top: 5px solid #E69A28; border-bottom: 5px solid #E69A28;
  box-shadow: 0 0 1.2em rgba(0,0,0,.25); padding: 12px 18px; margin: 8px 0 14px 0;
  font-family: 'Crimson Text', serif; color: #1E140C;
}
.statblock h3 { margin: 0; font-size: 1.45rem; color: #922610 !important; font-variant: small-caps; }
.statblock h4 { margin: 10px 0 4px 0; font-size: 1.05rem; color: #922610 !important;
  border-bottom: 1px solid #922610; font-variant: small-caps; }
.statblock .sub { font-style: italic; color: #3C2A1A; margin-bottom: 6px; }
.statblock .rule { height: 5px; margin: 6px 0;
  background: linear-gradient(10deg, rgba(0,0,0,0) 45%, #922610 49%, #922610 51%, rgba(0,0,0,0) 55%),
              linear-gradient(90deg, #922610, rgba(146,38,16,0)); background-size: 100% 100%; }
.statblock table { border-collapse: collapse; margin: 6px 0; font-size: .95rem; }
.statblock td, .statblock th { border-bottom: 1px solid #E0C9A0; padding: 2px 10px; text-align: center; }
.statblock th { color: #922610; }
.badge { display: inline-block; padding: 1px 9px; border-radius: 10px; font-size: .78rem; margin-right: 6px;
  font-family: 'Cinzel', serif; font-weight: 700; letter-spacing: .4px; }
.badge.official { background: #922610; color: #FDF1DC; }
.badge.extension { background: #3F5A3A; color: #F3E6C9; }
.badge.type { background: #E8D5AE; color: #58180D; border: 1px solid #C9A34E; }

/* Answer scroll */
.scroll {
  background: #FFF8E7; border: 2px solid #C9A34E; border-radius: 6px; padding: 16px 20px;
  box-shadow: inset 0 0 30px rgba(201,163,78,.25), 0 3px 10px rgba(0,0,0,.15);
  font-size: 1.15rem; line-height: 1.5;
}
.scroll .seal { float: right; font-size: 2rem; }

/* Quest log steps */
.step { border-left: 4px solid #C9A34E; background: rgba(253,241,220,.75); padding: 6px 12px; margin: 6px 0;
  border-radius: 0 6px 6px 0; }
.step.err { border-left-color: #B22222; background: rgba(255,225,225,.75); }
.step .t { font-family: 'Cinzel', serif; font-weight: 700; color: #58180D; }
.step code { font-size: .82rem; background: #F3E6C9; }

/* KPI tiles */
.kpi { background: #FDF1DC; border: 1px solid #C9A34E; border-radius: 8px; padding: 8px 10px; text-align: center;
  box-shadow: 0 2px 6px rgba(0,0,0,.12); }
.kpi .v { font-family: 'Cinzel', serif; font-size: 1.45rem; font-weight: 900; color: #922610; }
.kpi .l { font-size: .85rem; color: #5A3B22; text-transform: uppercase; letter-spacing: .6px; }

/* Difficulty gauge */
.gauge { position: relative; height: 26px; border-radius: 13px; overflow: hidden; border: 2px solid #58180D;
  background: linear-gradient(90deg, #6B8E23 0%, #6B8E23 33%, #DAA520 33%, #DAA520 66%, #B22222 66%, #B22222 100%); }
.gauge .needle { position: absolute; top: -4px; width: 4px; height: 34px; background: #1E140C; box-shadow: 0 0 4px #fff; }
.verdict { font-family: 'Cinzel', serif; font-size: 2rem; font-weight: 900; text-align: center; margin: 6px 0; }

.stButton > button { font-family: 'Cinzel', serif !important; border: 1px solid #922610; background: #FDF1DC;
  color: #58180D; border-radius: 6px; }
.stButton > button:hover { background: #922610; color: #FDF1DC; border-color: #58180D; }
div[data-testid="stExpander"] { background: rgba(253,241,220,.6); border: 1px solid #C9A34E; border-radius: 6px; }
.small { font-size: .85rem; color: #5A3B22; }
</style>
"""


def md_to_html(text: str) -> str:
    """Tiny Markdown -> HTML for stat blocks: headers, bold/italic, tables, paragraphs."""
    out, table = [], []

    def inline(s: str) -> str:
        s = html.escape(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", s)
        return s

    def flush_table():
        if not table:
            return
        rows = [r for r in table if not re.match(r"^\|?\s*:?-{2,}", r)]
        cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
        h = "".join(f"<th>{inline(c)}</th>" for c in cells[0])
        body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>" for row in cells[1:])
        out.append(f"<table><tr>{h}</tr>{body}</table>")
        table.clear()

    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.strip().startswith("|"):
            table.append(line)
            continue
        flush_table()
        if line.startswith("# "):
            out.append(f"<h3>{inline(line[2:])}</h3>")
        elif line.startswith("## "):
            out.append(f"<h4>{inline(line[3:])}</h4>")
        elif line.startswith("[") and line.endswith("]") and i == 0:
            continue   # contextual header of strategy C: shown as badges instead
        elif line.startswith("*") and i <= 2 and "Source:" in line:
            out.append(f'<div class="sub">{inline(line)}</div><div class="rule"></div>')
        elif line.strip() == "":
            out.append("")
        else:
            out.append(f"<div>{inline(line)}</div>")
    flush_table()
    return "\n".join(out)


def badges(doc: dict) -> str:
    tier = doc.get("tier", "extension")
    label = "Official SRD" if tier == "official" else "Open extension"
    icon = TYPE_ICON.get(doc.get("type"), "📜")
    return (f'<span class="badge {tier}">{label}</span>'
            f'<span class="badge type">{icon} {doc.get("type", "").replace("_", " ")}</span>'
            f'<span class="small">{html.escape(doc.get("source", ""))}</span>')


def statblock(doc: dict, max_chars: int = 4000) -> str:
    text = doc["text"][:max_chars] + ("…" if len(doc["text"]) > max_chars else "")
    return f'<div class="statblock">{badges(doc)}{md_to_html(text)}</div>'


def kpi(value, label) -> str:
    return f'<div class="kpi"><div class="v">{html.escape(str(value))}</div><div class="l">{html.escape(label)}</div></div>'
