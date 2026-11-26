"""The agent loop's failure handling, tested with a scripted fake model (no API key needed)."""
import json
from types import SimpleNamespace as NS

from src import agent, llm


def fake_response(calls=None, content=None, tin=100, tout=10):
    tool_calls = [NS(id=f"c{i}", function=NS(name=n, arguments=json.dumps(a) if isinstance(a, dict) else a))
                  for i, (n, a) in enumerate(calls or [])]
    return NS(choices=[NS(message=NS(content=content, tool_calls=tool_calls or None))],
              usage=NS(prompt_tokens=tin, completion_tokens=tout))


def script(monkeypatch, responses):
    it = iter(responses)

    def fake_chat(messages, tools=None, **kw):
        r = next(it)
        llm._record("chat", r.usage, 0.01)
        return r
    monkeypatch.setattr(agent.llm, "chat", fake_chat)


def test_hallucinated_tool_is_counted_and_recovered(monkeypatch):
    script(monkeypatch, [
        fake_response([("summon_dragon", {"x": 1})]),                       # failure mode 2
        fake_response([("dice_stats", {"expression": "8d6"})]),
        fake_response([("final_answer", {"answer": "28 on average", "citations": ["srd-2024_fireball"]})]),
    ])
    r = agent.run_agent("avg fireball?", log=False)
    assert r["terminated_by"] == "final_answer" and r["answer"] == "28 on average"
    assert r["hallucinated_calls"] == 1 and r["tool_errors"] == 1
    assert '"average": 28.0' in r["trace"][1]["observation"]


def test_max_iterations_stops_a_loop(monkeypatch):
    script(monkeypatch, [fake_response([("roll_dice", {"expression": "1d20"})])] * 3)   # failure mode 1
    r = agent.run_agent("loop forever", max_iterations=3, log=False)
    assert r["terminated_by"] == "max_iterations" and r["iterations"] == 3 and r["answer"] is None


def test_tool_error_becomes_an_observation(monkeypatch):
    script(monkeypatch, [
        fake_response([("encounter_difficulty", {"party_levels": [99], "monsters": []})]),   # failure mode 3
        fake_response(content="Sorry, levels go from 1 to 20."),
    ])
    r = agent.run_agent("bad level", log=False)
    assert r["trace"][0]["observation"].startswith("Error: tool 'encounter_difficulty' failed")
    assert r["terminated_by"] == "text"


def test_cost_is_metered(monkeypatch):
    script(monkeypatch, [fake_response([("final_answer", {"answer": "ok", "citations": []})], tin=1000, tout=100)])
    r = agent.run_agent("q", log=False)
    assert r["tokens_in"] == 1000 and abs(r["cost_usd"] - (1000 * 0.15 + 100 * 0.60) / 1e6) < 1e-9
