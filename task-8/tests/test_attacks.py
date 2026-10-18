"""Pytest-тесты red-team атак (для CI).

Запуск: pytest tests/test_attacks.py -v
Требует запущенные агенты (docker compose up).
"""
import os
import json
import urllib.request

import pytest

from payloads import PAYLOADS
from judges import evaluate

VULN_URL = os.getenv("VULN_URL", "http://localhost:8001")
PROT_URL = os.getenv("PROT_URL", "http://localhost:8002")


def _chat(url, message):
    data = json.dumps({"message": message}).encode()
    req = urllib.request.Request(f"{url}/chat", data=data,
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


@pytest.fixture(scope="session")
def vuln_ok():
    with urllib.request.urlopen(f"{VULN_URL}/health", timeout=10) as r:
        assert r.status == 200


@pytest.fixture(scope="session")
def prot_ok():
    with urllib.request.urlopen(f"{PROT_URL}/health", timeout=10) as r:
        assert r.status == 200


@pytest.mark.parametrize("p", PAYLOADS, ids=[p["id"] for p in PAYLOADS])
def test_vulnerable_attack_succeeds(p, vuln_ok):
    """Каждая атака должна проходить на уязвимой версии."""
    resp = _chat(VULN_URL, p["payload"])
    ev = evaluate(resp["response"], p["success_indicators"])
    assert ev["attack_succeeded"], (
        f"Expected attack {p['id']} to succeed on vulnerable agent, "
        f"but it was blocked. Response: {resp['response'][:300]}"
    )


@pytest.mark.parametrize("p", PAYLOADS, ids=[p["id"] for p in PAYLOADS])
def test_protected_attack_blocked(p, prot_ok):
    """Каждая атака должна быть заблокирована на защищённой версии."""
    resp = _chat(PROT_URL, p["payload"])
    ev = evaluate(resp["response"], p["success_indicators"])
    assert not ev["attack_succeeded"], (
        f"Expected attack {p['id']} to be blocked on protected agent, "
        f"but it leaked. Response: {resp['response'][:300]}"
    )
