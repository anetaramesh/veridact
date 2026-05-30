from __future__ import annotations
import pytest
from fastapi.testclient import TestClient


CLEAN_PAYLOAD = {
    "action_type": "wire_transfer",
    "parameters": {"amount": 500, "recipient_id": "LEGIT-USER", "account_id": "ACC-GOOD"},
    "context": {},
    "agent_id": "agent-001",
}


def test_clean_transaction_approved(client: TestClient):
    resp = client.post("/validate", json=CLEAN_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert data["approved"] is True
    assert data["violations"] == []
    assert data["latency_ms"] >= 0
    assert "request_id" in data


def test_sanctions_block(client: TestClient):
    payload = {**CLEAN_PAYLOAD, "parameters": {**CLEAN_PAYLOAD["parameters"], "recipient_id": "SDN-001"}}
    resp = client.post("/validate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["approved"] is False
    codes = [v["violation_code"] for v in data["violations"]]
    assert "OFAC_SANCTIONS_MATCH" in codes


def test_wire_threshold_block(client: TestClient):
    payload = {**CLEAN_PAYLOAD, "parameters": {**CLEAN_PAYLOAD["parameters"], "amount": 1_500_000}}
    resp = client.post("/validate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["approved"] is False
    codes = [v["violation_code"] for v in data["violations"]]
    assert "WIRE_THRESHOLD_EXCEEDED" in codes


def test_frozen_account_block(client: TestClient):
    payload = {**CLEAN_PAYLOAD, "parameters": {**CLEAN_PAYLOAD["parameters"], "account_id": "FROZEN-ACC-001"}}
    resp = client.post("/validate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["approved"] is False
    codes = [v["violation_code"] for v in data["violations"]]
    assert "ACCOUNT_FROZEN" in codes


def test_multiple_violations(client: TestClient):
    payload = {
        "action_type": "wire_transfer",
        "parameters": {
            "amount": 2_000_000,
            "recipient_id": "SDN-002",
            "account_id": "FROZEN-ACC-002",
        },
        "context": {},
        "agent_id": "agent-bad",
    }
    resp = client.post("/validate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["approved"] is False
    codes = {v["violation_code"] for v in data["violations"]}
    assert codes == {"OFAC_SANCTIONS_MATCH", "WIRE_THRESHOLD_EXCEEDED", "ACCOUNT_FROZEN"}


def test_threshold_boundary_exact(client: TestClient):
    """Exactly at threshold should pass (> not >=)."""
    payload = {**CLEAN_PAYLOAD, "parameters": {**CLEAN_PAYLOAD["parameters"], "amount": 1_000_000}}
    resp = client.post("/validate", json=payload)
    data = resp.json()
    assert data["approved"] is True


def test_response_has_rationale(client: TestClient):
    resp = client.post("/validate", json=CLEAN_PAYLOAD)
    data = resp.json()
    assert isinstance(data["rationale"], str) and len(data["rationale"]) > 0


@pytest.mark.asyncio
async def test_async_endpoint(async_client):
    resp = await async_client.post("/validate", json=CLEAN_PAYLOAD)
    assert resp.status_code == 200
    assert resp.json()["approved"] is True
