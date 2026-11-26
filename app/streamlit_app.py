"""DM Copilot — the visual front-end.  Run:  streamlit run app/streamlit_app.py

Pages: 🧙 Oracle (agent) · 📚 Library (retrieval explorer) · ⚔️ Encounter Forge (tools) ·
       📊 Hall of Records (evaluation + instrumentation) · 🗺️ Architecture
"""
import json
import os
import sys
from collections import Counter
from html import escape as html_escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd            # noqa: E402
import streamlit as st         # noqa: E402

from app.theme import CSS, TOOL_ICON, TOOL_LABEL, TYPE_ICON, kpi, statblock  # noqa: E402
from src import llm, tools      # noqa: E402
from src.chunking import STRATEGIES  # noqa: E402
from src.config import (DEFAULT_STRATEGY, INDEX_DIR, LOGS_DIR, RESULTS_DIR,  # noqa: E402
                        SEARCH_MODE, has_api_key)

st.set_page_config(page_title="DM Copilot", page_icon="🐉", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)


# ----------------------------------------------------------------------------- cached resources
@st.cache_resource(show_spinner="Opening the great library…")
def retriever(strategy: str):
    from src.retrieval import get_retriever
    return get_retriever(strategy)


@st.cache_resource
def doc_store():
    return tools.store()


@st.cache_data
def creature_names(official_only: bool):
    s = doc_store()["by_id"].values()
    names = sorted({d["name"] for d in s if d["type"] == "creature" and isinstance(d["meta"].get("xp"), int)
                    and (not official_only or d["source_key"] == "srd-2024")})
    return names


def get_doc(doc_id: str):
    return doc_store()["by_id"].get(doc_id)


def langfuse_on() -> bool:
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


if "history" not in st.session_state:
    st.session_state.history = []
if "session_meter" not in st.session_state:
    st.session_state.session_meter = {"questions": 0, "tokens_in": 0, "tokens_out": 0, "usd": 0.0, "latency": 0.0}

# ----------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("<h1 style='text-align:center;margin-bottom:0'>🐉</h1>"
                "<h2 style='text-align:center;margin-top:0;color:#E4C98F !important'>DM Copilot</h2>"
                "<p style='text-align:center;font-style:italic;margin-top:-10px'>The game master's grimoire</p>",
                unsafe_allow_html=True)
    page = st.radio("Navigate", ["🧙 The Oracle", "📚 The Library", "⚔️ Encounter Forge",
                                 "📊 Hall of Records", "🗺️ Architecture"], label_visibility="collapsed")
    st.markdown("---")
    dense_ready = (INDEX_DIR / DEFAULT_STRATEGY / "embeddings.npy").exists()
    st.markdown(f"{'🟢' if has_api_key() else '🔴'} OpenRouter key  \n"
                f"{'🟢' if dense_ready else '🟠'} FAISS index ({f'agent search: {SEARCH_MODE}' if dense_ready else 'BM25 only'})  \n"
                f"{'🟢' if langfuse_on() else '⚪'} Langfuse tracing")
    m = st.session_state.session_meter
    st.markdown("---")
    st.markdown("**This session**")
    st.markdown(f"Questions: **{m['questions']}**  \nTokens: **{m['tokens_in']:,}** in / **{m['tokens_out']:,}** out  \n"
                f"Cost: **${m['usd']:.4f}**  \nAvg latency: **{(m['latency'] / m['questions']) if m['questions'] else 0:.1f}s**")
    st.markdown("---")
    st.caption("Open content only — includes material from the System Reference Document 5.2.1 and 5.1 "
               "(CC BY 4.0, see README) and OGL 1.0a / CC BY extensions served by Open5e. "
               "Compatible with fifth edition.")


def hero(title: str, subtitle: str):
    st.markdown(f'<div class="hero"><h1>{title}</h1><p>{subtitle}</p></div>', unsafe_allow_html=True)


# ============================================================================= 🧙 ORACLE
def page_oracle():
    hero("🧙 The Oracle", "Ask anything about monsters, spells, items or rules — the Oracle searches, rolls and computes.")
    if not has_api_key():
        st.error("The Oracle needs an OpenRouter key: copy `.env.example` to `.env`, set `OPENROUTER_API_KEY`, restart.")
        return
    examples = {
        "⚔️ 2 Trolls vs four level-5 heroes": "How difficult is an encounter with 2 Trolls for a party of four level 5 characters? What should my players exploit?",
        "🔥 Fireball at 5th level": "What is the average damage of a Fireball cast with a 5th-level spell slot, and can it kill a Troll in one hit?",
        "🇫🇷 Question en français": "Combien de points de vie a un Troll selon les règles 2024, et comment l'empêcher de se régénérer ?",
        "👁️ Beholder (trap)": "What are the stats of a Beholder?",
        "🐲 Dragon duel": "Compare the Adult Red Dragon and the Adult Blue Dragon: challenge rating, hit points and breath weapon.",
        "🎲 Roll for me": "Roll a d20 with advantage plus 5 for my rogue's Stealth check, and tell me if she beats a passive Perception of 15.",
    }
    cols = st.columns(3)
    clicked = None
    for i, (label, q) in enumerate(examples.items()):
        if cols[i % 3].button(label, use_container_width=True):
            clicked = q
    c1, c2 = st.columns([5, 1])
    question = c1.text_input("Your question", value=clicked or "", placeholder="e.g. What are a Lich's legendary actions?",
                             label_visibility="collapsed")
    inject = c2.toggle("🧪 Poison", help="Security demo: slip a malicious fake document into every search result "
                                         "(indirect prompt injection). The Oracle must ignore its instructions.")
    tools.INJECTION_DEMO["enabled"] = inject
    ask = st.button("🔮 Consult the Oracle", type="primary") or bool(clicked)

    if ask and question.strip():
        with st.status("The Oracle consults the archives…", expanded=True) as status:
            def on_step(s):
                icon = TOOL_ICON.get(s["tool"], "❓")
                args = s["arguments"] if len(s["arguments"]) < 160 else s["arguments"][:160] + "…"
                obs = s["observation"].replace("<", "&lt;")[:220]
                cls = "step" if s["ok"] else "step err"
                st.markdown(f'<div class="{cls}"><span class="t">{icon} {TOOL_LABEL.get(s["tool"], s["tool"])}</span> '
                            f'<code>{s["tool"]}({args})</code><br><span class="small">↳ {obs}…</span>'
                            f'<span class="small" style="float:right">{s["model_latency_s"] + s["tool_latency_s"]:.1f}s</span></div>',
                            unsafe_allow_html=True)
            from src.agent import run_agent
            try:
                res = run_agent(question, on_step=on_step)
            except Exception as e:
                status.update(label=f"The Oracle failed: {e}", state="error")
                return
            status.update(label=f"Done — {res['iterations']} iterations, {res['tool_calls']} tool calls, "
                                f"{res['latency_s']:.1f}s", state="complete", expanded=False)
        sm = st.session_state.session_meter
        sm["questions"] += 1; sm["tokens_in"] += res["tokens_in"]; sm["tokens_out"] += res["tokens_out"]
        sm["usd"] += res["cost_usd"]; sm["latency"] += res["latency_s"]
        st.session_state.history.insert(0, {"q": question, "res": res, "poisoned": inject})
        st.rerun()   # refresh the sidebar meter

    for i, h in enumerate(st.session_state.history[:6]):
        render_answer(h, first=(i == 0))


def render_answer(h, first: bool):
    res = h["res"]
    if not first:
        st.markdown("---")
    st.markdown(f"#### ❓ {h['q']}" + ("  🧪 *(poisoned search results)*" if h.get("poisoned") else ""))
    if first:
        log = "".join(
            f'<div class="{"step" if s["ok"] else "step err"}"><span class="t">{TOOL_ICON.get(s["tool"], "❓")} '
            f'{TOOL_LABEL.get(s["tool"], s["tool"])}</span> <code>{s["tool"]}({html_escape(s["arguments"][:140])})</code>'
            f'<span class="small" style="float:right">{s["model_latency_s"] + s["tool_latency_s"]:.1f}s</span></div>'
            for s in res["trace"])
        st.markdown(f"<p class='cinzel' style='margin:4px 0'>📜 Quest log</p>{log}", unsafe_allow_html=True)
    answer = res["answer"] or f"*(no final answer — terminated by {res['terminated_by']})*"
    # blank lines around the answer let Streamlit render its Markdown inside the styled box
    st.markdown(f'<div class="scroll"><span class="seal">🪶</span>\n\n{answer}\n\n</div>', unsafe_allow_html=True)
    c = st.columns(7)
    tiles = [(res["iterations"], "iterations"), (res["tool_calls"], "tool calls"),
             (res["hallucinated_calls"], "bad calls"), (f"{res['tokens_in']:,}", "tokens in"),
             (f"{res['tokens_out']:,}", "tokens out"), (f"${res['cost_usd']:.4f}", "cost"),
             (f"{res['latency_s']:.1f}s", "latency")]
    for col, (v, l) in zip(c, tiles):
        col.markdown(kpi(v, l), unsafe_allow_html=True)
    cited = [get_doc(d) for d in res.get("citations", [])]
    cited = [d for d in cited if d]
    if cited:
        st.markdown("##### 📜 Sources cited")
        for d in cited:
            with st.expander(f"{TYPE_ICON.get(d['type'], '📜')} {d['name']} — {d['source']}", expanded=first and len(cited) <= 2):
                st.markdown(statblock(d), unsafe_allow_html=True)
    with st.expander("🔎 Full trace (tool calls and observations)"):
        for s in res["trace"]:
            st.markdown(f"**[{s['iteration']}] {TOOL_ICON.get(s['tool'], '')} `{s['tool']}`** "
                        f"({'ok' if s['ok'] else 'ERROR'}, {s['call_kind']})")
            st.code(s["arguments"], language="json")
            st.text(s["observation"][:1500])


# ============================================================================= 📚 LIBRARY
def page_library():
    hero("📚 The Library", "8,500+ open entries — see how BM25, dense vectors and their fusion retrieve them.")
    docs = list(doc_store()["by_id"].values())
    c = st.columns(4)
    c[0].markdown(kpi(f"{len(docs):,}", "documents"), unsafe_allow_html=True)
    c[1].markdown(kpi(len({d['source_key'] for d in docs}), "source books"), unsafe_allow_html=True)
    c[2].markdown(kpi(f"{sum(d['tier'] == 'official' for d in docs):,}", "official SRD"), unsafe_allow_html=True)
    c[3].markdown(kpi(f"{sum(len(d['text'].split()) for d in docs) / 1e6:.2f}M", "words"), unsafe_allow_html=True)

    q = st.text_input("Search the stacks", value="a giant that regrows lost limbs unless burned by fire or acid",
                      placeholder="Try a name (Fireball) or a description (a chest that bites)")
    f1, f2, f3 = st.columns([2, 2, 1])
    strategy = f1.selectbox("Chunking strategy", list(STRATEGIES), index=list(STRATEGIES).index(DEFAULT_STRATEGY),
                            format_func=lambda s: f"{s} — {STRATEGIES[s]}")
    type_ = f2.selectbox("Entry type", ["(all)"] + sorted(TYPE_ICON), format_func=lambda t: f"{TYPE_ICON.get(t, '📚')} {t}")
    official = f3.toggle("Official only")
    filters = {"type": None if type_ == "(all)" else type_, "official_only": official}
    r = retriever(strategy)
    rerank = st.toggle("➕ Show LLM rerank column (1 extra API call)", value=False) if has_api_key() else False
    modes = (["bm25", "dense", "hybrid"] + (["hybrid+rerank"] if rerank else [])) if r.idx.has_dense else ["bm25"]
    if not r.idx.has_dense:
        st.warning("Dense index not built yet for this strategy — BM25 only. Run `python -m src.index`.")
    if q.strip():
        st.markdown("### ⚖️ Retrievers side by side (top 5)")
        cols = st.columns(len(modes))
        results = {}
        for col, mode in zip(cols, modes):
            ids = r.search(q, mode=mode, k=5, filters=filters)
            results[mode] = ids
            col.markdown(f"**{ {'bm25': '🔤 BM25 (exact words)', 'dense': '🧠 Dense (meaning)', 'hybrid': '🔀 Hybrid (RRF)', 'hybrid+rerank': '⚖️ Hybrid + LLM rerank'}[mode] }**")
            for rank, cid in enumerate(ids, 1):
                ch = r.chunk(cid)
                col.markdown(f"{rank}. {TYPE_ICON.get(ch['type'], '')} **{ch['name']}**  \n"
                             f"<span class='small'>{ch['source']}</span>", unsafe_allow_html=True)
        best = results.get("hybrid") or results["bm25"]
        st.markdown("### 📖 Entries")
        for cid in best:
            d = get_doc(r.chunk(cid)["doc_id"])
            with st.expander(f"{TYPE_ICON.get(d['type'], '')} {d['name']} — {d['source']}"):
                st.markdown(statblock(d), unsafe_allow_html=True)
                st.caption(f"doc_id: {d['doc_id']} · matched chunk: {cid} · licence: {d['license']}")

    with st.expander("📊 What is in the library?"):
        a, b = st.columns(2)
        a.bar_chart(pd.Series(Counter(d["type"] for d in docs)).sort_values(ascending=False), color="#922610")
        b.bar_chart(pd.Series(Counter(d["source"] for d in docs)).sort_values(ascending=False), color="#3F5A3A")


# ============================================================================= ⚔️ ENCOUNTER FORGE
def page_forge():
    hero("⚔️ Encounter Forge", "The agent's tools, by hand: official SRD 5.2.1 encounter budgets and a dice tower.")
    left, right = st.columns([3, 2])
    with left:
        st.markdown("### 🛡️ The party")
        p1, p2 = st.columns(2)
        n = p1.number_input("Characters", 1, 8, 4)
        lvl = p2.slider("Level", 1, 20, 5)
        st.markdown("### 👹 The foes")
        official = st.toggle("Official 2024 monsters only", value=True)
        picks = st.multiselect("Monsters", creature_names(official), default=["Troll"] if "Troll" in creature_names(official) else [])
        monsters = []
        if picks:
            cc = st.columns(min(len(picks), 4))
            for i, name in enumerate(picks):
                monsters.append({"name": name, "count": cc[i % len(cc)].number_input(f"{name} ×", 1, 30, 1, key=f"cnt_{name}")})
    with right:
        if monsters:
            res = json.loads(tools.encounter_difficulty([lvl] * n, monsters))
            b = res["budget"]
            color = {"LOW": "#6B8E23", "MODERATE": "#B8860B", "HIGH": "#B22222"}.get(res["difficulty"], "#4B0000")
            st.markdown(f'<div class="verdict" style="color:{color}">{res["difficulty"]}</div>', unsafe_allow_html=True)
            scale = b["high"] * 1.5
            pos = min(res["total_xp"] / scale, 1.0) * 100
            g, y, r = (b["low"] / scale * 100, b["moderate"] / scale * 100, b["high"] / scale * 100)
            bg = (f"linear-gradient(90deg, #6B8E23 0%, #6B8E23 {g:.1f}%, #DAA520 {g:.1f}%, #DAA520 {y:.1f}%, "
                  f"#B22222 {y:.1f}%, #B22222 {r:.1f}%, #4B0000 {r:.1f}%, #4B0000 100%)")
            st.markdown(f'<div class="gauge" style="background:{bg}"><div class="needle" style="left:calc({pos:.1f}% - 2px)"></div></div>'
                        f'<p class="small" style="text-align:center">Total XP <b>{res["total_xp"]:,}</b> — '
                        f'Low ≤ {b["low"]:,} · Moderate ≤ {b["moderate"]:,} · High ≤ {b["high"]:,}</p>',
                        unsafe_allow_html=True)
            st.dataframe(pd.DataFrame(res["monsters"])[["name", "cr", "xp_each", "count", "xp_total"]],
                         hide_index=True, use_container_width=True)
            st.caption(res["rule"])
    if monsters:
        st.markdown("### 📜 Stat blocks")
        cols = st.columns(2)
        for i, m in enumerate(monsters):
            d = tools.find_doc(m["name"], type_="creature")
            if d:
                cols[i % 2].markdown(statblock(d, 2600), unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 🎲 The Dice Tower")
    d1, d2, d3 = st.columns([2, 1, 3])
    expr = d1.text_input("Expression", "2d20kh1+5", help="NdM+K · 2d20kh1 = advantage · 2d20kl1 = disadvantage")
    if d2.button("🎲 Roll!", use_container_width=True):
        try:
            roll = json.loads(tools.roll_dice(expr))
            stats = json.loads(tools.dice_stats(expr))
            d3.markdown(f'<div class="verdict" style="color:#922610">🎲 {roll["total"]}</div>'
                        f'<p class="small" style="text-align:center">{roll["rolls"]} · min {stats["min"]} · '
                        f'avg {stats["average"]} · max {stats["max"]}</p>', unsafe_allow_html=True)
        except Exception as e:
            d3.error(str(e))


# ============================================================================= 📊 HALL OF RECORDS
def page_records():
    hero("📊 Hall of Records", "Nothing works until it is scored on a held-out golden set — with cost and latency.")
    t1, t2, t3 = st.tabs(["🔍 Retrieval", "🤖 Agent", "📡 Live instrumentation"])
    with t1:
        p = RESULTS_DIR / "retrieval_metrics.csv"
        if not p.exists():
            st.info("Run `python -m src.evaluate retrieval` to fill this page.")
        else:
            df = pd.read_csv(p)
            split = st.radio("Split", ["test", "dev", "all"], horizontal=True)
            sub = df[df["split"] == split].copy()
            sub["config"] = sub["strategy"] + " · " + sub["mode"]
            best = sub.sort_values(["P@5", "MRR"], ascending=False).iloc[0]
            c = st.columns(4)
            c[0].markdown(kpi(best["config"], "best config"), unsafe_allow_html=True)
            c[1].markdown(kpi(f"{best['P@5']:.3f}", "precision@5"), unsafe_allow_html=True)
            c[2].markdown(kpi(f"{best['MRR']:.3f}", "MRR"), unsafe_allow_html=True)
            c[3].markdown(kpi(f"{best['R@5']:.3f}", "recall@5"), unsafe_allow_html=True)
            st.bar_chart(sub.set_index("config")[["P@5", "MRR"]], color=["#922610", "#C9A34E"], stack=False)
            st.dataframe(sub[["strategy", "mode", "P@5", "R@5", "MRR", "nDCG@5"]], hide_index=True, use_container_width=True)
            st.caption("Chunking: " + " · ".join(f"{k} = {v}" for k, v in STRATEGIES.items())
                       + ". Doc-level gold, k = 5. precision@5 is capped by the number of gold documents per question.")
            pc = RESULTS_DIR / "retrieval_by_category.csv"
            if pc.exists():
                st.markdown("**By question category (test split)**")
                cat = pd.read_csv(pc)
                st.dataframe(cat.pivot_table(index="category", columns=["strategy", "mode"], values="MRR").round(2),
                             use_container_width=True)
    with t2:
        p = RESULTS_DIR / "agent_metrics.json"
        if not p.exists():
            st.info("Run `python -m src.evaluate agent` to fill this page.")
        else:
            s = json.loads(p.read_text())
            c = st.columns(4)
            c[0].markdown(kpi(f"{s['success_rate'] * 100:.0f}%", "success rate"), unsafe_allow_html=True)
            c[1].markdown(kpi(f"{(s['trap_refusal_rate'] or 0) * 100:.0f}%", "trap refusals"), unsafe_allow_html=True)
            c[2].markdown(kpi(f"{s['faithfulness_mean']:.2f}", "faithfulness"), unsafe_allow_html=True)
            c[3].markdown(kpi(f"{s['hallucinated_tool_call_rate'] * 100:.1f}%", "bad tool calls"), unsafe_allow_html=True)
            c = st.columns(4)
            c[0].markdown(kpi(s["mean_iterations"], "mean iterations"), unsafe_allow_html=True)
            c[1].markdown(kpi(f"${s['cost_per_question_usd']:.4f}", "cost / question"), unsafe_allow_html=True)
            c[2].markdown(kpi(f"{s['latency_p50_s']}s", "latency p50"), unsafe_allow_html=True)
            c[3].markdown(kpi(f"{s['latency_p95_s']}s", "latency p95"), unsafe_allow_html=True)
            st.caption(f"{s['questions']} held-out questions · terminated by: {s['terminated_by']}")
            v1p, devp = RESULTS_DIR / "agent_metrics_v1.json", RESULTS_DIR / "agent_metrics_dev.json"
            if v1p.exists():
                v1 = json.loads(v1p.read_text())
                keys = ["success_rate", "trap_refusal_rate", "faithfulness_mean", "mean_iterations",
                        "hallucinated_tool_call_rate", "cost_per_question_usd", "latency_p50_s", "latency_p95_s"]
                comp = pd.DataFrame({"v1 (first run)": [v1.get(k) for k in keys], "v2 (after error analysis)": [s.get(k) for k in keys]},
                                    index=keys)
                if devp.exists():
                    comp["v2 on dev split"] = [json.loads(devp.read_text()).get(k) for k in keys]
                st.markdown("**Error analysis → fix → re-measure** (v1 failures: loops on absent monsters, "
                            "'HARD' instead of the tool's 'HIGH' label)")
                st.dataframe(comp, use_container_width=True)
            runs = RESULTS_DIR / "agent_runs.csv"
            if runs.exists():
                df = pd.read_csv(runs)
                st.dataframe(df[["id", "category", "success", "faithfulness", "iterations", "tools_used",
                                 "cost_usd", "latency_s", "question", "answer"]], hide_index=True, use_container_width=True)
    with t3:
        p = LOGS_DIR / "agent_runs.jsonl"
        if not p.exists():
            st.info("Ask the Oracle a question: every run is logged here (tokens, latency, tool calls).")
        else:
            rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()][-50:]
            df = pd.DataFrame([{"time": r.get("ts"), "question": r["question"][:80], "iterations": r["iterations"],
                                "tool_calls": r["tool_calls"], "bad_calls": r["hallucinated_calls"],
                                "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"],
                                "cost_usd": r["cost_usd"], "latency_s": r["latency_s"],
                                "tools": " > ".join(s["tool"] for s in r["trace"])} for r in rows])
            c = st.columns(4)
            c[0].markdown(kpi(len(df), "logged runs"), unsafe_allow_html=True)
            c[1].markdown(kpi(f"{df['latency_s'].median():.1f}s", "median latency"), unsafe_allow_html=True)
            c[2].markdown(kpi(f"${df['cost_usd'].sum():.4f}", "total cost"), unsafe_allow_html=True)
            c[3].markdown(kpi(f"{df['tokens_in'].mean():,.0f}", "avg tokens in"), unsafe_allow_html=True)
            st.line_chart(df[["latency_s"]], color="#922610")
            st.dataframe(df.iloc[::-1], hide_index=True, use_container_width=True)
        builds = [json.loads((INDEX_DIR / s / "build_stats.json").read_text()) for s in STRATEGIES
                  if (INDEX_DIR / s / "build_stats.json").exists()]
        if builds:
            st.markdown("**Index build cost (paid once, offline)**")
            st.dataframe(pd.DataFrame(builds), hide_index=True)


# ============================================================================= 🗺️ ARCHITECTURE
DOT = """
digraph G {
  rankdir=LR; bgcolor="transparent"; node [shape=box, style="rounded,filled", fontname="Georgia",
  fillcolor="#FDF1DC", color="#922610", fontcolor="#2B1B10"]; edge [color="#58180D"];
  subgraph cluster_off { label="OFFLINE (once)"; fontname="Georgia"; color="#C9A34E"; style=dashed;
    api [label="Open5e API v2\\n+ SRD 5.2.1 PDF"]; ingest [label="ingest.py\\n8,528 documents\\n(Markdown + metadata)"];
    chunk [label="chunking.py\\nA fixed · B structure\\nC structure + header"];
    emb [label="mistral-embed\\n(1024-d, cached)"]; faiss [label="FAISS\\nIndexFlatIP"]; bm25 [label="BM25\\n(k1=1.5, b=0.75)"];
    api -> ingest -> chunk -> emb -> faiss; chunk -> bm25; }
  subgraph cluster_on { label="ONLINE (per question)"; fontname="Georgia"; color="#C9A34E"; style=dashed;
    user [label="Game master\\n(Streamlit UI)", fillcolor="#E8D5AE"];
    agent [label="Agent loop\\nMistral Small 4\\nmax 8 iterations\\n+ token budget", fillcolor="#F6D7C3"];
    tools [label="Tools\\nsearch_library · get_entry\\nroll_dice · dice_stats\\nencounter_difficulty · final_answer"];
    ret [label="Retrieval (strategy C)\\nagent: dense FAISS\\ncompared: BM25 · RRF hybrid\\n· hybrid + LLM rerank"];
    answer [label="Cited answer\\n(doc_ids)", fillcolor="#E8D5AE"];
    logs [label="Instrumentation\\ntokens · cost · latency\\ntool calls → JSONL / Langfuse", fillcolor="#EFE3C8"];
    user -> agent -> tools -> ret; tools -> agent [label="observations"]; agent -> answer -> user; agent -> logs; }
  faiss -> ret; bm25 -> ret;
  eval [label="evaluate.py\\ngolden set (dev / held-out test)\\nP@5 · MRR · success · cost", fillcolor="#EFE3C8"];
  ret -> eval [style=dotted]; agent -> eval [style=dotted];
}
"""


def page_architecture():
    hero("🗺️ Architecture", "From open books to a cited answer — the data flow of DM Copilot.")
    st.graphviz_chart(DOT, use_container_width=True)
    st.markdown("""
| Stage | Choice | Why |
|---|---|---|
| Corpus | Open5e API v2 (21 books) + SRD 5.2.1 PDF | everything open (CC BY 4.0 / OGL 1.0a), ≥ 500 docs |
| Chunking | 3 strategies compared | a stat block cut in half loses its meaning |
| Retrieval | dense FAISS for the agent (best on the dev split); BM25, RRF hybrid and LLM rerank compared | measured, not assumed — exact names also go through `get_entry` |
| Agent | hand-written loop, 6 tools, `final_answer` + 8 iterations + token budget | the 3 failure modes of Session 6 |
| Safety | retrieved text wrapped as untrusted `<document>` data | indirect prompt injection |
| Evaluation | golden set, dev / held-out test | P@5, MRR, success, faithfulness, cost, latency |
""")


{"🧙 The Oracle": page_oracle, "📚 The Library": page_library, "⚔️ Encounter Forge": page_forge,
 "📊 Hall of Records": page_records, "🗺️ Architecture": page_architecture}[page]()
