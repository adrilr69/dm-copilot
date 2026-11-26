"""Step 3 — chunking. Three strategies, compared in the evaluation (results/retrieval_*.csv).

A. fixed     — fixed windows of 200 words with a 50-word overlap (exactly the Session 5 lab).
               Blind to structure: a stat block can be cut in the middle of an attack.
B. structure — one chunk per game entry; long entries (classes, big monsters) are split on their
               "## " sections, packed up to MAX_WORDS. A stat block is never cut in half.
C. contextual — B, plus a one-line header prepended to every chunk
               ("[Creature | Troll | CR 5 | System Reference Document 5.2]") so that the second
               chunk of a long entry still says which entry it belongs to.

Each chunk keeps its document's metadata, so every citation can name its source book.
"""
from typing import Dict, List

MAX_WORDS = 350
STRATEGIES = {
    "A": "Fixed 200 words / 50 overlap",
    "B": "Structure-aware (1 entry = 1 chunk, split on sections)",
    "C": "Structure-aware + contextual header",
}


def fixed_windows(text: str, c: int = 200, o: int = 50) -> List[str]:
    """Chunk i covers words[i*(c-o) : i*(c-o)+c] (Session 5 lab, unchanged)."""
    words = text.split()
    step, out, start = c - o, [], 0
    while start < len(words):
        out.append(" ".join(words[start:start + c]))
        start += step
    return out


def _split_long_block(block: str, max_words: int) -> List[str]:
    """A single section longer than max_words: pack its paragraphs, then hard-cut if needed."""
    parts, cur = [], []
    for para in block.split("\n"):
        if cur and len(" ".join(cur + [para]).split()) > max_words:
            parts.append("\n".join(cur))
            cur = []
        cur.append(para)
    if cur:
        parts.append("\n".join(cur))
    final = []
    for p in parts:
        final += fixed_windows(p, max_words, 0) if len(p.split()) > max_words else [p]
    return final


def structure_chunks(text: str, max_words: int = MAX_WORDS) -> List[str]:
    if len(text.split()) <= max_words:
        return [text]
    # sections start with "\n## " ; the first block is the entry header + stats
    blocks, cur = [], []
    for line in text.split("\n"):
        if line.startswith("## ") and cur:
            blocks.append("\n".join(cur).strip())
            cur = []
        cur.append(line)
    blocks.append("\n".join(cur).strip())
    chunks, pack = [], ""
    for b in blocks:
        if len(b.split()) > max_words:
            if pack:
                chunks.append(pack)
                pack = ""
            chunks += _split_long_block(b, max_words)
        elif pack and len((pack + "\n\n" + b).split()) > max_words:
            chunks.append(pack)
            pack = b
        else:
            pack = (pack + "\n\n" + b) if pack else b
    if pack:
        chunks.append(pack)
    return [c for c in chunks if c.strip()]


def context_header(doc: Dict) -> str:
    m = doc.get("meta", {})
    bits = [doc["type"].replace("_", " ").title(), doc["name"]]
    if doc["type"] == "creature" and m.get("cr") is not None:
        bits.append(f"CR {m['cr']:g}")
    if doc["type"] == "spell" and m.get("level") is not None:
        bits.append(f"level {m['level']}")
    if doc["type"] == "magic_item" and m.get("rarity"):
        bits.append(m["rarity"])
    bits.append(doc["source"])
    return "[" + " | ".join(bits) + "]"


def chunk_documents(docs: List[Dict], strategy: str) -> List[Dict]:
    out = []
    for d in docs:
        if strategy == "A":
            pieces = fixed_windows(d["text"])
        else:
            pieces = structure_chunks(d["text"])
            if strategy == "C":
                h = context_header(d)
                pieces = [f"{h}\n{p}" for p in pieces]
        for j, p in enumerate(pieces):
            out.append({"chunk_id": f"{d['doc_id']}#c{j}", "doc_id": d["doc_id"], "n": j,
                        "name": d["name"], "type": d["type"], "source": d["source"],
                        "source_key": d["source_key"], "tier": d["tier"], "text": p})
    return out
