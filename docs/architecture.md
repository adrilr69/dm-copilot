# DM Copilot — architecture data-flow

```mermaid
flowchart LR
    subgraph OFF["OFFLINE — run once"]
        A["Open5e API v2<br/>21 open books<br/>+ SRD 5.2.1 PDF extract"] --> B["ingest.py<br/>8,528 documents<br/>Markdown + metadata"]
        B --> C["chunking.py<br/>A fixed 200/50<br/>B structure-aware<br/>C structure + header"]
        C --> D["mistral-embed<br/>1024-d, L2-normalised<br/>cached .npy"]
        D --> E[("FAISS<br/>IndexFlatIP")]
        C --> F[("BM25<br/>k1=1.5 b=0.75")]
    end

    subgraph UI["FRONT-ENDS"]
        TA["🎲 Table app<br/>FastAPI + HTML/JS<br/>combat · dice · oracle · forge"]
        LD["📊 Lab dashboard<br/>Streamlit"]
    end
    TA -->|"/api/ask (SSE stream)"| G
    TA -->|"/api/roll · /api/encounter"| T
    TA -->|"/api/search"| R
    LD --> G
    subgraph ON["ONLINE — per question"]
        U["Game master"] --> TA
        G["Agent loop<br/>Mistral Small 4<br/>max 8 iterations + token budget"]
        G -->|tool call| T["Tools registry<br/>search_library · get_entry<br/>roll_dice · dice_stats<br/>encounter_difficulty · final_answer"]
        T -->|observation| G
        T --> R["Retrieval, strategy C<br/>agent: dense FAISS (best on dev)<br/>compared: BM25 · RRF hybrid · LLM rerank"]
        G --> ANS["Cited answer<br/>doc_ids"] --> U
        G --> L["Instrumentation<br/>tokens · cost · latency · tool calls<br/>logs/agent_runs.jsonl + Langfuse"]
    end

    E --> R
    F --> R
    R -.-> EV["evaluate.py<br/>golden set dev / held-out test<br/>P@5 · MRR · success · faithfulness · cost · latency"]
    G -.-> EV
```

## Failure handling (Session 6)

| Failure mode | Mitigation in the code | Signal measured |
|---|---|---|
| Non-terminating loop | `final_answer` tool + `MAX_ITERATIONS = 8` + `TOKEN_BUDGET` (`src/agent.py`) | iterations, `terminated_by` |
| Hallucinated tool call | `validate_args` against the JSON schema, unknown tools rejected with the list of real tools (`src/tools.py`) | `hallucinated_calls` / tool calls |
| Error cascade | every tool error returned to the model as an `Error: ...` observation; LLM calls retried with exponential backoff (`src/llm.py`) | `tool_errors` |
| Indirect prompt injection | retrieved text wrapped in `<document>` tags flagged as untrusted data; system prompt forbids following it; 🧪 Poison toggle in the UI to demo it | manual demo |
| Out-of-library question | system prompt + golden-set traps (Beholder, Mind Flayer…) | trap refusal rate |
