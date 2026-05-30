from __future__ import annotations
import pytest
from fastapi.testclient import TestClient


CLEAN_PAYLOAD = {
    "action_type": "wire_transfer",
    "parameters": {"amount": 500, "recipient_id": "LEGIT-USER", "account_id": "ACC-GOOD", "customer_id": "CUST-001"},
    "context": {},
    "agent_id": "agent-001",
}


def test_clean_transaction_approved(client: TestClient):
    resp = client.post("/validate", json=CLEAN_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert data["approved"] is True
    # flag-severity violations don't block approval but may appear in violations list
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
    # KYC_MISSING_FIELDS (2090), OFAC match (3310+ofac_sanctions), wire threshold (3110+finra_wire_threshold), account frozen (4511+finra_account_freeze)
    assert "OFAC_SANCTIONS_MATCH" in codes
    assert "WIRE_THRESHOLD_EXCEEDED" in codes
    assert "ACCOUNT_FROZEN" in codes
    assert "KYC_MISSING_FIELDS" in codes
    assert data["approved"] is False


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
