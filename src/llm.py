"""The only module that talks to the LLM provider.

Same discipline as the Session 4-6 labs:
- OpenRouter speaks the OpenAI protocol -> the `openai` SDK, pointed at OpenRouter.
- No SDK-level retries: `chat()` / `embed()` own the retry policy (exponential backoff).
- Every call is metered: tokens in/out, latency, USD (price table in config.py).
"""
import time
from dataclasses import dataclass, field
from typing import List, Optional

from openai import OpenAI

from src.config import (CHAT_MODEL, EMBED_MODEL, OPENROUTER_API_KEY, OPENROUTER_BASE_URL,
                        PRICES)

MAX_ATTEMPTS = 5
FATAL_STATUS = (400, 401, 402, 403, 404, 422)   # retrying will not help
ROUTE = {"provider": {"order": ["Mistral"]}}    # pin the Mistral provider: honest prices

_client: Optional[OpenAI] = None


def client() -> OpenAI:
    global _client
    if _client is None:
        if not OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY is missing: copy .env.example to .env and set it.")
        _client = OpenAI(api_key=OPENROUTER_API_KEY, base_url=OPENROUTER_BASE_URL, max_retries=0,
                         default_headers={"X-Title": "DM Copilot (student project)"})
    return _client


@dataclass
class Meter:
    """Counts tokens, calls and latency. One global meter + one per question if needed."""
    chat_in: int = 0
    chat_out: int = 0
    embed_in: int = 0
    calls: int = 0
    latency_s: float = 0.0
    events: List[dict] = field(default_factory=list)

    def add(self, kind: str, usage, latency: float):
        tin = getattr(usage, "prompt_tokens", None) or getattr(usage, "total_tokens", 0) or 0
        tout = getattr(usage, "completion_tokens", 0) or 0
        if kind == "chat":
            self.chat_in += tin
            self.chat_out += tout
        else:
            self.embed_in += tin
        self.calls += 1
        self.latency_s += latency
        self.events.append({"kind": kind, "tokens_in": tin, "tokens_out": tout,
                            "latency_s": round(latency, 3)})

    @property
    def usd(self) -> float:
        return (self.chat_in * PRICES["chat_in"] + self.chat_out * PRICES["chat_out"]
                + self.embed_in * PRICES["embed_in"]) / 1e6

    def snapshot(self) -> dict:
        return {"chat_in": self.chat_in, "chat_out": self.chat_out, "embed_in": self.embed_in,
                "calls": self.calls, "latency_s": round(self.latency_s, 3),
                "usd": round(self.usd, 6)}


METER = Meter()   # global meter for the whole process
_extra_meters: List[Meter] = []


class track:
    """Context manager: `with track() as m:` meters every call made inside the block."""

    def __enter__(self) -> Meter:
        self.m = Meter()
        _extra_meters.append(self.m)
        return self.m

    def __exit__(self, *exc):
        _extra_meters.remove(self.m)
        return False


def _record(kind: str, usage, latency: float):
    METER.add(kind, usage, latency)
    for m in _extra_meters:
        m.add(kind, usage, latency)


def _with_retry(fn, label: str):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as e:
            status = getattr(e, "status_code", None)
            if status in FATAL_STATUS or attempt == MAX_ATTEMPTS:
                raise
            wait = 2 ** attempt
            print(f"  {label}: {type(e).__name__} (attempt {attempt}/{MAX_ATTEMPTS}) — retry in {wait}s")
            time.sleep(wait)


def chat(messages, tools=None, response_format=None, temperature: float = 0.0):
    """One chat call (optionally with tools or a pydantic response_format), metered."""
    kwargs = dict(model=CHAT_MODEL, messages=messages, temperature=temperature, extra_body=ROUTE)
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    def _call():
        if response_format is not None:
            return client().beta.chat.completions.parse(response_format=response_format, **kwargs)
        return client().chat.completions.create(**kwargs)

    t0 = time.perf_counter()
    r = _with_retry(_call, "chat")
    _record("chat", r.usage, time.perf_counter() - t0)
    return r


def embed(texts: List[str]) -> List[List[float]]:
    """A batch of texts -> list of 1024-dim vectors, metered."""
    t0 = time.perf_counter()
    r = _with_retry(lambda: client().embeddings.create(model=EMBED_MODEL, input=texts), "embed")
    _record("embed", r.usage, time.perf_counter() - t0)
    return [d.embedding for d in r.data]
