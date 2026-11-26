"""Step 8 — evaluation on the golden set. Nothing is "working" until it is scored here.

Retrieval (doc-level gold, k = 5):
    precision@5 and MRR (the project metrics) + Recall@5 and nDCG@5,
    for 3 chunking strategies x 3 retrievers (BM25, dense, hybrid) + hybrid+rerank on strategy C.
Agent (end to end):
    success rate, refusal rate on out-of-library traps, faithfulness (LLM judge, RAGAS-style),
    mean iterations, hallucinated-tool-call rate, cost per question, latency p50 / p95.

The golden set is split into dev (used while tuning) and test (held out, reported).
Run:  python -m src.evaluate retrieval      python -m src.evaluate agent      python -m src.evaluate all
"""
import json
import math
import sys
import time
from statistics import mean, median
from typing import Dict, List

import pandas as pd
from pydantic import BaseModel, Field

from src import llm
from src.config import EVAL_DIR, RESULTS_DIR

K = 5


# ----------------------------------------------------------------------------- metrics
def recall_at_k(ranked: List[str], gold: List[str], k: int) -> float:
    return len(set(ranked[:k]) & set(gold)) / len(set(gold))


def precision_at_k(ranked: List[str], gold: List[str], k: int) -> float:
    return len(set(ranked[:k]) & set(gold)) / k


def mrr(ranked: List[str], gold: List[str]) -> float:
    for i, d in enumerate(ranked, start=1):
        if d in set(gold):
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: List[str], gold: List[str], k: int) -> float:
    g = set(gold)
    dcg = sum(1.0 / math.log2(i + 1) for i, d in enumerate(ranked[:k], start=1) if d in g)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(g), k) + 1))
    return dcg / idcg if idcg else 0.0


def load_golden() -> List[Dict]:
    with (EVAL_DIR / "golden_set.jsonl").open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ----------------------------------------------------------------------------- retrieval
def eval_retrieval(strategies=("A", "B", "C"), modes=("bm25", "dense", "hybrid"),
                   rerank_strategy: str = "C"):
    from src.retrieval import Retriever
    gold_set = [g for g in load_golden() if g.get("gold")]
    rows, per_q = [], []
    configs = [(s, m) for s in strategies for m in modes]
    if rerank_strategy:
        configs.append((rerank_strategy, "hybrid+rerank"))
    retrievers = {}
    for s, mode in configs:
        r = retrievers.setdefault(s, Retriever(s))
        if mode != "bm25" and not r.idx.has_dense:
            print(f"[{s}/{mode}] skipped: no embeddings (run python -m src.index {s})")
            continue
        t0 = time.time()
        with llm.track() as meter:
            for g in gold_set:
                ranked_chunks = r.search(g["question"], mode=mode, k=10)
                ranked = r.doc_ids(ranked_chunks)
                per_q.append({"strategy": s, "mode": mode, "id": g["id"], "split": g["split"],
                              "category": g["category"], "question": g["question"],
                              "P@5": precision_at_k(ranked, g["gold"], K),
                              "R@5": recall_at_k(ranked, g["gold"], K),
                              "MRR": mrr(ranked, g["gold"]), "nDCG@5": ndcg_at_k(ranked, g["gold"], K),
                              "top5": " | ".join(ranked[:5])})
        print(f"[{s}/{mode}] {len(gold_set)} questions in {time.time() - t0:.1f}s, ${meter.usd:.4f}")
    df = pd.DataFrame(per_q)
    df.to_csv(RESULTS_DIR / "retrieval_per_question.csv", index=False)
    for split in ("dev", "test", "all"):
        sub = df if split == "all" else df[df["split"] == split]
        agg = (sub.groupby(["strategy", "mode"])[["P@5", "R@5", "MRR", "nDCG@5"]]
               .mean().round(3).reset_index())
        agg.insert(0, "split", split)
        rows.append(agg)
    table = pd.concat(rows)
    table.to_csv(RESULTS_DIR / "retrieval_metrics.csv", index=False)
    print(table[table["split"] == "test"].to_string(index=False))
    by_cat = (df[df["split"] == "test"].groupby(["category", "strategy", "mode"])[["P@5", "MRR"]]
              .mean().round(3).reset_index())
    by_cat.to_csv(RESULTS_DIR / "retrieval_by_category.csv", index=False)
    return table


# ----------------------------------------------------------------------------- agent
class Claim(BaseModel):
    claim: str
    supported: bool


class FaithfulnessVerdict(BaseModel):
    claims: List[Claim] = Field(default_factory=list)


JUDGE_SYSTEM = ("You check an answer against the evidence a tool-using assistant retrieved. Split the "
                "answer into atomic factual claims (ignore greetings and meta remarks), and mark each claim "
                "supported=true only if the evidence FULLY supports it. Return them via the schema.")

REFUSAL_MARKERS = ["not in the library", "not part of", "no entry", "not found", "isn't in", "is not in",
                   "not available", "n'est pas", "pas dans", "introuvable", "ne figure pas", "aucune entrée",
                   "not open content", "not included", "absent", "not present", "pas présent",
                   "pas disponible", "not part of the open"]


def faithfulness(answer: str, trace: List[Dict]) -> float:
    evidence = "\n\n".join(s["observation"][:2500] for s in trace if s["tool"] != "final_answer")[:12000]
    if not answer or not evidence:
        return float("nan")
    r = llm.chat([{"role": "system", "content": JUDGE_SYSTEM},
                  {"role": "user", "content": f"Evidence:\n{evidence}\n\nAnswer:\n{answer}"}],
                 response_format=FaithfulnessVerdict)
    claims = r.choices[0].message.parsed.claims if r.choices[0].message.parsed else []
    return sum(c.supported for c in claims) / len(claims) if claims else float("nan")


def is_success(g: Dict, answer: str) -> bool:
    a = (answer or "").lower().replace("*", "").replace("_", " ")   # ignore Markdown emphasis
    if not g.get("answerable", True):
        return any(m in a for m in REFUSAL_MARKERS)
    # every group must be matched; a group is a list of acceptable alternatives
    return all(any(alt.lower() in a for alt in group) for group in g.get("expected", []))


def eval_agent(splits=("test",), tag: str = ""):
    from src.agent import run_agent
    qs = [g for g in load_golden() if g["split"] in splits and g.get("agent", True)]
    runs = []
    for i, g in enumerate(qs, start=1):  # noqa: B007
        res = run_agent(g["question"], log=False)
        with llm.track() as judge_meter:
            f = faithfulness(res["answer"], res["trace"]) if g.get("answerable", True) else float("nan")
        runs.append({"id": g["id"], "category": g["category"], "question": g["question"],
                     "answer": res["answer"], "citations": " ".join(res["citations"]),
                     "success": is_success(g, res["answer"]), "faithfulness": f,
                     "terminated_by": res["terminated_by"], "iterations": res["iterations"],
                     "tool_calls": res["tool_calls"], "hallucinated_calls": res["hallucinated_calls"],
                     "tool_errors": res["tool_errors"], "tokens_in": res["tokens_in"],
                     "tokens_out": res["tokens_out"], "cost_usd": res["cost_usd"],
                     "judge_cost_usd": round(judge_meter.usd, 6), "latency_s": res["latency_s"],
                     "tools_used": " > ".join(s["tool"] for s in res["trace"])})
        print(f"{i:2d}/{len(qs)} {'OK  ' if runs[-1]['success'] else 'FAIL'} {res['iterations']} it "
              f"{res['latency_s']:5.1f}s  {g['question'][:70]}")
    df = pd.DataFrame(runs)
    df.to_csv(RESULTS_DIR / f"agent_runs{tag}.csv", index=False)
    return summarize(df, splits, tag)


def rescore(tag: str = ""):
    """Re-apply is_success to saved answers (no new API call) — used after fixing the scorer."""
    gold = {g["id"]: g for g in load_golden()}
    df = pd.read_csv(RESULTS_DIR / f"agent_runs{tag}.csv")
    df["success"] = [is_success(gold[i], a if isinstance(a, str) else "") for i, a in zip(df["id"], df["answer"])]
    df.to_csv(RESULTS_DIR / f"agent_runs{tag}.csv", index=False)
    old = json.loads((RESULTS_DIR / f"agent_metrics{tag}.json").read_text())
    return summarize(df, old["splits"], tag)


def summarize(df: pd.DataFrame, splits, tag: str = "") -> Dict:
    lat = sorted(df["latency_s"])
    traps = df[df["category"] == "out_of_library"]
    summary = {
        "questions": len(df), "splits": list(splits),
        "success_rate": round(df["success"].mean(), 3),
        "trap_refusal_rate": round(traps["success"].mean(), 3) if len(traps) else None,
        "faithfulness_mean": round(df["faithfulness"].dropna().mean(), 3),
        "mean_iterations": round(df["iterations"].mean(), 2),
        "hallucinated_tool_call_rate": round(df["hallucinated_calls"].sum() / max(df["tool_calls"].sum(), 1), 4),
        "terminated_by": df["terminated_by"].value_counts().to_dict(),
        "cost_per_question_usd": round(df["cost_usd"].mean(), 5),
        "total_cost_usd": round(df["cost_usd"].sum() + df["judge_cost_usd"].sum(), 4),
        "latency_p50_s": round(median(lat), 2),
        "latency_p95_s": round(lat[min(len(lat) - 1, int(0.95 * len(lat)))], 2),
        "mean_tokens_in": round(df["tokens_in"].mean()), "mean_tokens_out": round(df["tokens_out"].mean()),
    }
    (RESULTS_DIR / f"agent_metrics{tag}.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("retrieval", "all"):
        eval_retrieval()
    if what in ("agent", "all"):
        eval_agent(("test",))                 # held-out, reported
        eval_agent(("dev",), tag="_dev")      # the split used while tuning prompts
    print("meter:", llm.METER.snapshot())
