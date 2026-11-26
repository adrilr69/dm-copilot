"""Step 4 — embed the chunks once (offline), build the FAISS and BM25 indexes.

- Dense: mistral-embed (1024 dims), L2-normalised -> FAISS IndexFlatIP (inner product == cosine).
- Lexical: BM25 (k1=1.5, b=0.75), rebuilt in memory at load time (a few seconds, free).
- Embeddings are cached on disk per strategy: the corpus is paid for ONCE.

Run:  python -m src.index            (builds strategies A, B, C)
      python -m src.index C          (only strategy C, the one the app uses)
"""
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List

import faiss
import numpy as np
from rank_bm25 import BM25Okapi
from tqdm import tqdm

from src.chunking import chunk_documents
from src.config import DOCS_PATH, EMBED_DIM, INDEX_DIR, has_api_key
from src import llm

MAX_BATCH_TOKENS = 12_000   # stay well under the provider's per-request limit
MAX_BATCH_ITEMS = 64
WORKERS = 4


def load_documents() -> List[Dict]:
    with DOCS_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def est_tokens(text: str) -> int:
    return int(len(text.split()) * 1.4) + 8


def make_batches(texts: List[str]) -> List[List[int]]:
    batches, cur, cur_tok = [], [], 0
    for i, t in enumerate(texts):
        tok = est_tokens(t)
        if cur and (cur_tok + tok > MAX_BATCH_TOKENS or len(cur) >= MAX_BATCH_ITEMS):
            batches.append(cur)
            cur, cur_tok = [], 0
        cur.append(i)
        cur_tok += tok
    if cur:
        batches.append(cur)
    return batches


def embed_texts(texts: List[str], workers: int = WORKERS, progress: bool = True) -> np.ndarray:
    """Batched, parallel, metered, L2-normalised embeddings."""
    batches = make_batches(texts)
    out = np.zeros((len(texts), EMBED_DIM), dtype="float32")

    def run(idx):
        vecs = llm.embed([texts[i][:20_000] for i in idx])
        return idx, vecs

    with ThreadPoolExecutor(max_workers=workers) as pool:
        it = pool.map(run, batches)
        for idx, vecs in tqdm(it, total=len(batches), desc="embed", disable=not progress):
            out[idx] = np.array(vecs, dtype="float32")
    out /= np.linalg.norm(out, axis=1, keepdims=True) + 1e-12
    return out


# Function words carry no signal for BM25 but dominate natural-language questions
# ("how many hit points does a troll have"): drop them (same idea as the Session 6 lab).
STOPWORDS = set("""a an the of and or to in on at by for with from into onto is are was were be been being do does
did doing have has had having what which who whom whose when where why how many much can could should would
will shall may might must i me my we our you your he she it its they them their this that these those there here
than then so as if about any some all each every no not only own same such too very just also up down out over
under again once more most other both few nor s t don get gets give tell explain describe""".split())


def tokenize(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]


def build(strategy: str):
    docs = load_documents()
    chunks = chunk_documents(docs, strategy)
    d = INDEX_DIR / strategy
    d.mkdir(parents=True, exist_ok=True)
    emb_path = d / "embeddings.npy"
    (d / "chunks.jsonl").write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in chunks),
                                    encoding="utf-8")
    if emb_path.exists() and np.load(emb_path, mmap_mode="r").shape[0] == len(chunks):
        print(f"[{strategy}] embeddings cached ({len(chunks)} chunks) — skipped")
        return
    if not has_api_key():
        print(f"[{strategy}] {len(chunks)} chunks written; no OPENROUTER_API_KEY -> BM25 only for now")
        return
    t0 = time.time()
    before = llm.METER.snapshot()
    m = embed_texts([c["text"] for c in chunks])
    np.save(emb_path, m.astype("float16"))   # float16 halves the disk size, cosine barely moves
    after = llm.METER.snapshot()
    stats = {"strategy": strategy, "chunks": len(chunks), "seconds": round(time.time() - t0, 1),
             "embed_tokens": after["embed_in"] - before["embed_in"],
             "usd": round(after["usd"] - before["usd"], 4)}
    (d / "build_stats.json").write_text(json.dumps(stats, indent=2))
    print(f"[{strategy}] {stats}")


class Index:
    """Everything retrieval needs for one chunking strategy, loaded in memory."""

    def __init__(self, strategy: str):
        d = INDEX_DIR / strategy
        self.strategy = strategy
        with (d / "chunks.jsonl").open(encoding="utf-8") as f:
            self.chunks = [json.loads(line) for line in f]
        self.pos = {c["chunk_id"]: i for i, c in enumerate(self.chunks)}
        self.bm25 = BM25Okapi([tokenize(c["text"]) for c in self.chunks], k1=1.5, b=0.75)
        emb_path = d / "embeddings.npy"
        self.has_dense = emb_path.exists()
        if self.has_dense:
            m = np.load(emb_path).astype("float32")
            self.faiss = faiss.IndexFlatIP(EMBED_DIM)
            self.faiss.add(m)


def main():
    strategies = sys.argv[1:] or ["A", "B", "C"]
    for s in strategies:
        build(s)
    print("meter:", llm.METER.snapshot())


if __name__ == "__main__":
    main()
