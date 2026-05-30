from __future__ import annotations

import time

import pytest
from httpx import AsyncClient

CLEAN_PAYLOAD = {
    "action_type": "wire_transfer",
    "parameters": {"amount": 500, "recipient_id": "LEGIT-USER", "account_id": "ACC-GOOD", "customer_id": "CUST-001"},
    "context": {},
    "agent_id": "agent-endpoint-test",
}


@pytest.mark.asyncio
async def test_valid_wire_transfer_passes(async_client: AsyncClient):
    resp = await async_client.post("/validate", json=CLEAN_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert data["approved"] is True
    assert data["outcome"] == "approved"
    FLAG_CODES = {
        "ACCOUNT_RECORD_INCOMPLETE", "ANALYSIS_TOOL_DISCLOSURE_MISSING",
        "ARBITRATION_DISCLOSURE_MISSING", "COMMERCIAL_HONOR_VIOLATION",
        "COMPLIANCE_CERTIFICATION_MISSING", "DISCRETIONARY_AUTHORIZATION_MISSING",
        "EXCESSIVE_COMMISSION", "EXEMPTED_SECURITY_REVIEW",
        "MEMBER_PRIVATE_PLACEMENT_FILING_MISSING", "MISLEADING_COMMUNICATION",
        "MUTUAL_FUND_PRICE_DEVIATION", "OFFERING_CONFLICT_DISCLOSURE_MISSING",
        "PRIVATE_SECURITIES_NOTICE_MISSING", "REGISTRATION_CATEGORY_MISMATCH",
        "RESEARCH_ANALYST_CONFLICT", "OUTSIDE_ACCOUNT_NOT_APPROVED",
        "TAPE_RECORDING_REQUIRED", "TRACE_REPORTING_MISSING",
        "UNDERWRITING_COMPENSATION_EXCESSIVE",
    }
    blocking = [v for v in data["violations"] if v["violation_code"] not in FLAG_CODES]
    assert blocking == []


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
