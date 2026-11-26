"""DM Copilot — Table app: the API the game-table interface talks to.

A thin FastAPI layer over the SAME pipeline as the rest of the project (src/): retrieval, tools,
agent, meter and logs. No logic is duplicated here — every number shown at the table comes from
the evaluated system.

Run:   python -m table.server            -> http://localhost:8000
       python -m table.server --lan      -> also reachable by your players' phones on the same Wi-Fi
"""
import json
import queue
import re
import sys
import threading
import webbrowser
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.theme import md_to_html                                  # noqa: E402
from src import llm, tools                                        # noqa: E402
from src.config import (DEFAULT_STRATEGY, LOGS_DIR, RESULTS_DIR,  # noqa: E402
                        SEARCH_MODE, has_api_key)

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="DM Copilot — Table")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

SUBTITLE_RE = re.compile(r"^\*(.+?)\*\s*—\s*Source:", re.M)
DEX_RE = re.compile(r"DEX \d+ \(([+-]\d+)\)")
HD_RE = re.compile(r"\*\*Hit Points\*\* \d+ \(([^)]+)\)")


def retriever():
    from src.retrieval import get_retriever
    return get_retriever(DEFAULT_STRATEGY)


def subtitle(doc) -> str:
    m = SUBTITLE_RE.search(doc["text"])
    return m.group(1) if m else doc["type"].replace("_", " ")


def combat_stats(doc) -> Optional[dict]:
    if doc["type"] != "creature":
        return None
    dex = DEX_RE.search(doc["text"])
    hd = HD_RE.search(doc["text"])
    m = doc["meta"]
    return {"hp": m.get("hp"), "ac": m.get("ac"), "cr": m.get("cr"), "xp": m.get("xp"),
            "init": int(dex.group(1)) if dex else 0,
            "hit_dice": hd.group(1).replace(" ", "") if hd else None}


def card(doc) -> dict:
    return {"doc_id": doc["doc_id"], "name": doc["name"], "type": doc["type"], "source": doc["source"],
            "tier": doc["tier"], "subtitle": subtitle(doc), "combat": combat_stats(doc)}


# ----------------------------------------------------------------------------- pages
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.on_event("startup")
def warm_up():
    tools.store()
    retriever()


# ----------------------------------------------------------------------------- read API
@app.get("/api/status")
def status():
    s = tools.store()["by_id"]
    return {"api_key": has_api_key(), "dense": retriever().idx.has_dense, "search_mode": SEARCH_MODE,
            "strategy": DEFAULT_STRATEGY, "documents": len(s),
            "books": len({d["source_key"] for d in s.values()}), "meter": llm.METER.snapshot()}


@app.get("/api/search")
def search(q: str, type: str = "", official: bool = False, k: int = 12):
    r = retriever()
    mode = SEARCH_MODE if (r.idx.has_dense and has_api_key()) else "bm25"
    ids = r.search(q, mode=mode, k=k, filters={"type": type or None, "official_only": official})
    by_id = tools.store()["by_id"]
    return {"mode": mode, "results": [card(by_id[r.chunk(c)["doc_id"]]) for c in ids]}


@app.get("/api/entry/{doc_id}")
def entry(doc_id: str):
    d = tools.store()["by_id"].get(doc_id) or tools.find_doc(doc_id)
    if not d:
        raise HTTPException(404, f"No entry '{doc_id}'")
    return {**card(d), "license": d["license"], "html": md_to_html(d["text"])}


@app.get("/api/creatures")
def creatures(q: str = "", official: bool = True, limit: int = 15):
    """Autocomplete for the combat tracker and the forge (official 2024 stat blocks first)."""
    qn = tools.norm(q)
    out = []
    for name, docs in tools.store()["by_name"].items():
        if qn and qn not in name:
            continue
        for d in docs:
            if d["type"] == "creature" and isinstance(d["meta"].get("xp"), int) and \
                    (not official or d["source_key"] == "srd-2024"):
                out.append((not name.startswith(qn), len(name), d))
                break
    out.sort(key=lambda t: (t[0], t[1]))
    return [card(d) for _, _, d in out[:limit]]


@app.get("/api/conditions")
def conditions():
    s = tools.store()["by_id"].values()
    return [{"name": d["name"], "doc_id": d["doc_id"], "html": md_to_html(d["text"])}
            for d in s if d["type"] == "condition" and d["source_key"] == "core"]


@app.get("/api/chronicles")
def chronicles():
    """Evaluation results + live instrumentation (the course's 'nothing works until it is scored')."""
    def read_json(name):
        p = RESULTS_DIR / name
        return json.loads(p.read_text()) if p.exists() else None
    retrieval = []
    p = RESULTS_DIR / "retrieval_metrics.csv"
    if p.exists():
        import pandas as pd
        df = pd.read_csv(p)
        retrieval = df[df["split"] == "test"].to_dict(orient="records")
    runs = []
    lp = LOGS_DIR / "agent_runs.jsonl"
    if lp.exists():
        for line in lp.read_text(encoding="utf-8").splitlines()[-30:]:
            r = json.loads(line)
            runs.append({k: r.get(k) for k in ("ts", "question", "iterations", "tool_calls", "hallucinated_calls",
                                               "tokens_in", "tokens_out", "cost_usd", "latency_s", "terminated_by")}
                        | {"tools": [s["tool"] for s in r.get("trace", [])]})
    return {"retrieval_test": retrieval, "agent_v2": read_json("agent_metrics.json"),
            "agent_v1": read_json("agent_metrics_v1.json"), "agent_dev": read_json("agent_metrics_dev.json"),
            "agent_v2_first": read_json("agent_metrics_v2_pre_multiattack.json"),
            "live_runs": runs[::-1], "meter": llm.METER.snapshot()}


# ----------------------------------------------------------------------------- tools
class RollIn(BaseModel):
    expression: str


@app.post("/api/roll")
def roll(body: RollIn):
    try:
        return {**json.loads(tools.roll_dice(body.expression)), "stats": json.loads(tools.dice_stats(body.expression))}
    except ValueError as e:
        raise HTTPException(400, str(e))


class Monster(BaseModel):
    name: str
    count: int = 1


class EncounterIn(BaseModel):
    party_levels: List[int]
    monsters: List[Monster]


@app.post("/api/encounter")
def encounter(body: EncounterIn):
    try:
        return json.loads(tools.encounter_difficulty(body.party_levels, [m.model_dump() for m in body.monsters]))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ----------------------------------------------------------------------------- the Oracle (agent), streamed
class AskIn(BaseModel):
    question: str
    poison: bool = False


@app.post("/api/ask")
def ask(body: AskIn):
    """Server-Sent Events: one `step` event per tool call while the agent works, then `final`."""
    if not has_api_key():
        raise HTTPException(503, "OPENROUTER_API_KEY missing in .env")
    from src.agent import run_agent
    events: "queue.Queue" = queue.Queue()

    def work():
        tools.INJECTION_DEMO["enabled"] = body.poison
        try:
            res = run_agent(body.question, on_step=lambda s: events.put(("step", s)))
            by_id = tools.store()["by_id"]
            res["cards"] = [card(by_id[c]) for c in res.get("citations", []) if c in by_id]
            events.put(("final", res))
        except Exception as e:  # the stream must always end cleanly
            events.put(("error", {"message": str(e)}))
        finally:
            tools.INJECTION_DEMO["enabled"] = False
            events.put(("end", {}))

    threading.Thread(target=work, daemon=True).start()

    def stream():
        while True:
            kind, payload = events.get()
            if kind == "end":
                break
            if kind == "step":
                payload = {**payload, "observation": payload["observation"][:400]}
            yield f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def main():
    import uvicorn
    lan = "--lan" in sys.argv
    port = 8000
    if "--no-browser" not in sys.argv:
        threading.Timer(2.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    uvicorn.run(app, host="0.0.0.0" if lan else "127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
