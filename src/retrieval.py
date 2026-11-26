"""Step 5 — retrieval: BM25 ‖ dense -> RRF fusion -> (optional) LLM rerank.

Same funnel as the Session 5 lab:
- BM25 reads the exact words: unbeatable on names ("Fireball", "Troll", "Bag of Holding").
- Dense reads the meaning: "the green giant that grows its arms back" -> Troll.
- RRF fuses ranks (scores live on different scales, ranks do not), k = 60.
- The LLM reranker reads question + candidate together and keeps the best few.

Results are returned at the DOCUMENT level (first chunk of each entry wins), so the three
chunking strategies can be compared on the same golden set of document ids.
"""
from collections import Counter, OrderedDict
from functools import lru_cache
from typing import Dict, List, Optional

import numpy as np
from pydantic import BaseModel, Field

from src import llm
from src.config import POOL_SIZE, RRF_K, TOP_K
from src.index import Index, embed_texts, tokenize

_QUERY_CACHE: "OrderedDict[str, np.ndarray]" = OrderedDict()


def embed_query(q: str) -> np.ndarray:
    """Query embedding, cached (the same query is reused across strategies and variants)."""
    if q not in _QUERY_CACHE:
        _QUERY_CACHE[q] = embed_texts([q], workers=1, progress=False)
        if len(_QUERY_CACHE) > 2000:
            _QUERY_CACHE.popitem(last=False)
    return _QUERY_CACHE[q]


def rrf_fuse(*ranked_lists: List[str], k: int = RRF_K) -> List[str]:
    """Reciprocal Rank Fusion: score(d) = sum over lists of 1 / (k + rank)."""
    scores = Counter()
    for lst in ranked_lists:
        for rank, cid in enumerate(lst, start=1):
            scores[cid] += 1.0 / (k + rank)
    return [cid for cid, _ in scores.most_common()]


class ChunkScore(BaseModel):
    number: int = Field(ge=1)
    score: float = Field(ge=0, le=10)


class RerankVerdict(BaseModel):
    scores: List[ChunkScore]


RERANK_SYSTEM = (
    "You are a relevance judge inside a retrieval system for Dungeons & Dragons game masters. "
    "You will see one question and numbered candidate passages. Score each candidate from 0 "
    "(irrelevant) to 10 (directly answers the question). Judge relevance to the question only. "
    "Return a score for every candidate, via the schema.")


class Retriever:
    def __init__(self, strategy: str):
        self.idx = Index(strategy)
        self.strategy = strategy

    # ------------------------------------------------------------------ filters
    def _allowed(self, c: Dict, filters: Optional[Dict]) -> bool:
        if not filters:
            return True
        if filters.get("type") and c["type"] != filters["type"]:
            return False
        if filters.get("official_only") and c["tier"] != "official":
            return False
        if filters.get("source_key") and c["source_key"] != filters["source_key"]:
            return False
        return True

    # ------------------------------------------------------------------ legs
    def bm25(self, q: str, k: int = POOL_SIZE, filters: Optional[Dict] = None) -> List[str]:
        scores = self.idx.bm25.get_scores(tokenize(q))
        order = np.argsort(-scores)
        out = []
        for i in order:
            if scores[i] <= 0:
                break
            c = self.idx.chunks[i]
            if self._allowed(c, filters):
                out.append(c["chunk_id"])
                if len(out) == k:
                    break
        return out

    def dense(self, q: str, k: int = POOL_SIZE, filters: Optional[Dict] = None) -> List[str]:
        if not self.idx.has_dense:
            return []
        fetch = k if not filters else min(len(self.idx.chunks), k * 25)
        _, ids = self.idx.faiss.search(embed_query(q), fetch)
        out = []
        for i in ids[0]:
            if i < 0:
                continue
            c = self.idx.chunks[i]
            if self._allowed(c, filters):
                out.append(c["chunk_id"])
                if len(out) == k:
                    break
        return out

    def hybrid(self, q: str, k: int = POOL_SIZE, filters: Optional[Dict] = None) -> List[str]:
        return rrf_fuse(self.bm25(q, POOL_SIZE, filters), self.dense(q, POOL_SIZE, filters))[:k]

    def rerank(self, q: str, candidate_ids: List[str], top: int = TOP_K) -> List[str]:
        """LLM-as-reranker: ONE structured-output call scores all candidates (Session 5 lab)."""
        if not candidate_ids:
            return []
        lines = [f"Question: {q}", "", "Candidates:"]
        for n, cid in enumerate(candidate_ids, start=1):
            lines.append(f"[{n}] {self.chunk(cid)['text'][:600]}")
        r = llm.chat([{"role": "system", "content": RERANK_SYSTEM},
                      {"role": "user", "content": "\n".join(lines)}], response_format=RerankVerdict)
        parsed = r.choices[0].message.parsed
        by_n = {s.number: s.score for s in (parsed.scores if parsed else [])}
        order = sorted(range(len(candidate_ids)), key=lambda n: -by_n.get(n + 1, 0.0))
        return [candidate_ids[n] for n in order[:top]]

    # ------------------------------------------------------------------ public API
    def search(self, q: str, mode: str = "hybrid", k: int = TOP_K,
               filters: Optional[Dict] = None) -> List[str]:
        """Return the top-k CHUNK ids (one per document) for a mode:
        'bm25' | 'dense' | 'hybrid' | 'hybrid+rerank'."""
        if mode == "bm25":
            pool = self.bm25(q, POOL_SIZE * 3, filters)
        elif mode == "dense":
            pool = self.dense(q, POOL_SIZE * 3, filters)
        else:
            pool = self.hybrid(q, POOL_SIZE * 3, filters)
        pool = self.one_per_doc(pool)
        if mode == "hybrid+rerank":
            return self.rerank(q, pool[:POOL_SIZE], top=k)
        return pool[:k]

    def one_per_doc(self, chunk_ids: List[str]) -> List[str]:
        seen, out = set(), []
        for cid in chunk_ids:
            d = self.chunk(cid)["doc_id"]
            if d not in seen:
                seen.add(d)
                out.append(cid)
        return out

    def chunk(self, cid: str) -> Dict:
        return self.idx.chunks[self.idx.pos[cid]]

    def doc_ids(self, chunk_ids: List[str]) -> List[str]:
        return [self.chunk(c)["doc_id"] for c in chunk_ids]


@lru_cache(maxsize=4)
def get_retriever(strategy: str) -> Retriever:
    return Retriever(strategy)
