"""The table app's API on its deterministic endpoints (no LLM call). Run: python -m pytest -q"""
import pytest
from fastapi.testclient import TestClient

from table.server import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_status(client):
    s = client.get("/api/status").json()
    assert s["documents"] >= 500 and s["books"] >= 10


def test_creature_autocomplete_gives_combat_stats(client):
    troll = client.get("/api/creatures", params={"q": "troll"}).json()[0]
    assert troll["name"] == "Troll" and troll["combat"] == {"hp": 94, "ac": 15, "cr": 5.0, "xp": 1800,
                                                             "init": 1, "hit_dice": "9d10+45"}


def test_entry_html(client):
    e = client.get("/api/entry/srd-2024_fireball").json()
    assert e["type"] == "spell" and "8d6" in e["html"] and e["combat"] is None


def test_roll_and_bad_roll(client):
    r = client.post("/api/roll", json={"expression": "3*(2d6+4)"}).json()
    assert 18 <= r["total"] <= 48 and r["stats"]["average"] == 33.0
    assert client.post("/api/roll", json={"expression": "drop table"}).status_code == 400


def test_encounter_by_doc_id(client):
    r = client.post("/api/encounter", json={"party_levels": [3, 3], "monsters": [
        {"name": "srd-2024_owlbear", "count": 1}, {"name": "srd-2024_wolf", "count": 1}]}).json()
    assert r["total_xp"] == 750 and r["difficulty"] == "HIGH"


def test_conditions(client):
    names = {c["name"] for c in client.get("/api/conditions").json()}
    assert {"Poisoned", "Grappled", "Prone"} <= names
