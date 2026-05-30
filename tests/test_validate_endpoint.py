from __future__ import annotations

import time

import pytest
from httpx import AsyncClient

CLEAN_PAYLOAD = {
    "action_type": "wire_transfer",
    "parameters": {"amount": 500, "recipient_id": "LEGIT-USER", "account_id": "ACC-GOOD"},
    "context": {},
    "agent_id": "agent-endpoint-test",
}


@pytest.mark.asyncio
async def test_valid_wire_transfer_passes(async_client: AsyncClient):
    resp = await async_client.post("/validate", json=CLEAN_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert data["approved"] is True
    assert data["violations"] == []
    assert data["outcome"] == "approved"


@pytest.mark.asyncio
async def test_ofac_flagged_recipient_blocks(async_client: AsyncClient):
    payload = {
        **CLEAN_PAYLOAD,
        "parameters": {**CLEAN_PAYLOAD["parameters"], "recipient_id": "SDN-001"},
    }
    resp = await async_client.post("/validate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["approved"] is False
    codes = [v["violation_code"] for v in data["violations"]]
    assert "OFAC_SANCTIONS_MATCH" in codes
    assert data["outcome"] == "hard_block"


@pytest.mark.asyncio
async def test_response_contains_audit_entry_id(async_client: AsyncClient):
    resp = await async_client.post("/validate", json=CLEAN_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert "audit_entry_id" in data
    # Must be a non-empty UUID string when audit write succeeds.
    assert len(data["audit_entry_id"]) > 0


@pytest.mark.asyncio
async def test_latency_header_is_accurate(async_client: AsyncClient):
    wall_start = time.perf_counter()
    resp = await async_client.post("/validate", json=CLEAN_PAYLOAD)
    wall_elapsed_ms = (time.perf_counter() - wall_start) * 1000

    assert resp.status_code == 200
    data = resp.json()
    reported_ms = data["latency_ms"]

    # Reported latency must be positive and not exceed the wall-clock time
    # by more than 500 ms (generous allowance for test-environment overhead).
    assert reported_ms > 0
    assert reported_ms <= wall_elapsed_ms + 500
