"""Central configuration: paths, models, prices. Every other module imports from here."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# --- Paths -------------------------------------------------------------------
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
DOCS_PATH = DATA_PROCESSED / "documents.jsonl"
INDEX_DIR = DATA_PROCESSED / "index"
EVAL_DIR = ROOT / "eval"
RESULTS_DIR = ROOT / "results"
LOGS_DIR = ROOT / "logs"
for _d in (DATA_RAW, DATA_PROCESSED, INDEX_DIR, RESULTS_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Models (the course stack: Mistral through OpenRouter) ---------------------
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
CHAT_MODEL = "mistralai/mistral-small-2603"     # Mistral Small 4
EMBED_MODEL = "mistralai/mistral-embed-2312"    # Mistral Embed, 1024 dims
EMBED_DIM = 1024

# USD per 1M tokens (same table as the Session 4-6 labs)
PRICES = {"chat_in": 0.15, "chat_out": 0.60, "embed_in": 0.10}

# --- Retrieval defaults --------------------------------------------------------
DEFAULT_STRATEGY = "C"      # chunking strategy used by the app and the agent (see chunking.py)
# Retriever used by the agent's search tool. Chosen on the DEV split (results/retrieval_metrics.csv):
# C·dense MRR 0.922 vs C·hybrid+rerank 0.917 vs C·hybrid 0.828 — dense wins on dev and needs no extra
# LLM call. Exact names are covered by the get_entry tool (exact lookup).
SEARCH_MODE = "dense"
RRF_K = 60                  # Cormack et al. 2009, same as the Session 5 lab
POOL_SIZE = 20              # candidates per retriever before fusion / rerank
TOP_K = 5                   # chunks handed to the LLM

# --- Agent ---------------------------------------------------------------------
MAX_ITERATIONS = 8          # hard bound on the agent loop (failure mode 1)
TOKEN_BUDGET = 40_000       # total prompt+completion tokens allowed per question


def has_api_key() -> bool:
    return bool(OPENROUTER_API_KEY)
