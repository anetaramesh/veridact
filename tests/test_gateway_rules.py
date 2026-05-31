"""Tests for payment gateway response code compliance rules and the
/validate/gateway-response endpoint.

Covers:
  - gateway_fraud_decline    (hard_block: 41, 43, 57, 516, R29, FRAUD, ...)
  - gateway_card_restriction (hard_block: 62, 78, 510-512, R07, R08, BLOCKED, ...)
  - gateway_limit_exceeded   (soft_hold: 61, 65, 513, 514, R01, LIMIT, ...)
  - gateway_insufficient_funds (soft_hold: 51, 506, R01, NSF, ...)
  - gateway_invalid_data     (flag: 14, 54, 82, 507-509, INVALID, EXPIRED, ...)
  - gateway_system_error     (soft_hold: 91, 96, 502-504, 517, TIMEOUT, ...)
  - /validate/gateway-response endpoint integration
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from httpx import AsyncClient

from src.engine.agt_adapter import AGTAdapter


RULES_DIR = Path(__file__).parent.parent / "rules"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_adapter(*rule_files: str) -> AGTAdapter:
    import tempfile, shutil
    tmp = Path(tempfile.mkdtemp())
    for name in rule_files:
        src = RULES_DIR / name
        if src.exists():
            shutil.copy(src, tmp / name)
    return AGTAdapter(rules_dir=tmp)


def _eval(adapter: AGTAdapter, action_type: str, gateway_response_code: str, **extra):
    params = {"gateway_response_code": gateway_response_code, **extra}
    return adapter.evaluate(action_type, params, {}, "test-agent")


# ===========================================================================
# 1. gateway_fraud_decline  (hard_block)
# ===========================================================================

class TestGatewayFraudDecline:
    """ISO 8583 and processor fraud codes → GATEWAY_FRAUD_DECLINE hard_block."""

    def setup_method(self):
        self.adapter = _make_adapter("gateway_fraud_decline.yaml")

    @pytest.mark.parametrize("code", [
        "41", "43", "57", "516", "R29",
        "FRAUD", "PICKUP", "STOLEN", "LOST", "DO_NOT_HONOR_FRAUD",
    ])
    def test_blocks_fraud_code(self, code: str):
        result = _eval(self.adapter, "wire_transfer", code)
        assert "GATEWAY_FRAUD_DECLINE" in result.violations
        assert result.approved is False

    @pytest.mark.parametrize("code", ["41", "FRAUD"])
    def test_blocks_on_all_covered_action_types(self, code: str):
        for action in ("wire_transfer", "ach_payment", "equity_trade", "loan_decision"):
            result = _eval(self.adapter, action, code)
            assert "GATEWAY_FRAUD_DECLINE" in result.violations, f"Expected block for action={action}"

    def test_passes_approved_code(self):
        result = _eval(self.adapter, "wire_transfer", "00")
        assert "GATEWAY_FRAUD_DECLINE" not in result.violations

    def test_passes_unrelated_decline_code(self):
        result = _eval(self.adapter, "wire_transfer", "51")  # insufficient funds, not fraud
        assert "GATEWAY_FRAUD_DECLINE" not in result.violations

    def test_case_insensitive_match(self):
        result = _eval(self.adapter, "wire_transfer", "fraud")
        assert "GATEWAY_FRAUD_DECLINE" in result.violations


# ===========================================================================
# 2. gateway_card_restriction  (hard_block)
# ===========================================================================

class TestGatewayCardRestriction:
    """Restricted / closed card codes → GATEWAY_CARD_RESTRICTED hard_block."""

    def setup_method(self):
        self.adapter = _make_adapter("gateway_card_restriction.yaml")

    @pytest.mark.parametrize("code", [
        "62", "78", "510", "511", "512",
        "R07", "R08",
        "RESTRICTED", "BLOCKED", "CLOSED", "ACCOUNT_CLOSED", "CARD_BLOCKED",
    ])
    def test_blocks_restricted_code(self, code: str):
        result = _eval(self.adapter, "wire_transfer", code)
        assert "GATEWAY_CARD_RESTRICTED" in result.violations
        assert result.approved is False

    def test_passes_approved_code(self):
        result = _eval(self.adapter, "wire_transfer", "00")
        assert "GATEWAY_CARD_RESTRICTED" not in result.violations

    def test_passes_nsf_code(self):
        # NSF is a different rule, should not match card restriction
        result = _eval(self.adapter, "wire_transfer", "51")
        assert "GATEWAY_CARD_RESTRICTED" not in result.violations

    def test_case_insensitive_match(self):
        result = _eval(self.adapter, "wire_transfer", "blocked")
        assert "GATEWAY_CARD_RESTRICTED" in result.violations


# ===========================================================================
# 3. gateway_limit_exceeded  (soft_hold)
# ===========================================================================

class TestGatewayLimitExceeded:
    """Velocity / limit codes → GATEWAY_LIMIT_EXCEEDED soft_hold."""

    def setup_method(self):
        self.adapter = _make_adapter("gateway_limit_exceeded.yaml")

    @pytest.mark.parametrize("code", [
        "61", "65", "513", "514", "R01",
        "LIMIT", "EXCEED", "VELOCITY", "OVER_LIMIT", "DAILY_LIMIT", "AMOUNT_LIMIT",
    ])
    def test_triggers_limit_exceeded(self, code: str):
        result = _eval(self.adapter, "wire_transfer", code)
        assert "GATEWAY_LIMIT_EXCEEDED" in result.violations

    def test_approved_by_default_as_flag_soft_hold(self):
        # soft_hold means approved=False (not a flag-only rule)
        result = _eval(self.adapter, "wire_transfer", "61")
        assert result.approved is False

    def test_passes_fraud_code(self):
        # Fraud codes are a separate rule
        result = _eval(self.adapter, "wire_transfer", "41")
        assert "GATEWAY_LIMIT_EXCEEDED" not in result.violations

    def test_passes_approved_code(self):
        result = _eval(self.adapter, "wire_transfer", "00")
        assert "GATEWAY_LIMIT_EXCEEDED" not in result.violations

    def test_does_not_apply_to_equity_trade(self):
        # gateway_limit_exceeded covers equity_trade
        result = _eval(self.adapter, "equity_trade", "61")
        assert "GATEWAY_LIMIT_EXCEEDED" in result.violations

    def test_does_not_apply_to_loan_decision(self):
        result = _eval(self.adapter, "loan_decision", "61")
        assert "GATEWAY_LIMIT_EXCEEDED" not in result.violations


# ===========================================================================
# 4. gateway_insufficient_funds  (soft_hold)
# ===========================================================================

class TestGatewayInsufficientFunds:
    """NSF codes → GATEWAY_INSUFFICIENT_FUNDS soft_hold."""

    def setup_method(self):
        self.adapter = _make_adapter("gateway_insufficient_funds.yaml")

    @pytest.mark.parametrize("code", [
        "51", "506", "R01", "R09",
        "NSF", "INSUFFICIENT", "NO_FUNDS", "UNCOLLECTED_FUNDS", "INSUFFICIENT_FUNDS",
    ])
    def test_triggers_insufficient_funds(self, code: str):
        result = _eval(self.adapter, "wire_transfer", code)
        assert "GATEWAY_INSUFFICIENT_FUNDS" in result.violations
        assert result.approved is False

    def test_passes_approved_code(self):
        result = _eval(self.adapter, "wire_transfer", "00")
        assert "GATEWAY_INSUFFICIENT_FUNDS" not in result.violations

    def test_passes_fraud_code(self):
        result = _eval(self.adapter, "wire_transfer", "41")
        assert "GATEWAY_INSUFFICIENT_FUNDS" not in result.violations

    def test_applies_to_ach(self):
        result = _eval(self.adapter, "ach_payment", "R01")
        assert "GATEWAY_INSUFFICIENT_FUNDS" in result.violations

    def test_does_not_apply_to_equity_trade(self):
        result = _eval(self.adapter, "equity_trade", "51")
        assert "GATEWAY_INSUFFICIENT_FUNDS" not in result.violations


# ===========================================================================
# 5. gateway_invalid_data  (flag)
# ===========================================================================

class TestGatewayInvalidData:
    """Invalid card data codes → GATEWAY_INVALID_CARD_DATA flag."""

    def setup_method(self):
        self.adapter = _make_adapter("gateway_invalid_data.yaml")

    @pytest.mark.parametrize("code", [
        "14", "54", "82", "507", "508", "509",
        "INVALID", "EXPIRED", "BAD_CVV", "LUHN",
        "INVALID_CARD", "INVALID_ACCOUNT", "INVALID_ROUTING", "FORMAT_ERROR",
    ])
    def test_flags_invalid_data_code(self, code: str):
        result = _eval(self.adapter, "wire_transfer", code)
        assert "GATEWAY_INVALID_CARD_DATA" in result.violations

    def test_flag_severity_still_approves(self):
        # flag severity means the action is logged but not blocked
        result = _eval(self.adapter, "wire_transfer", "54")
        assert result.approved is True  # flag does not block
        assert "GATEWAY_INVALID_CARD_DATA" in result.violations

    def test_passes_approved_code(self):
        result = _eval(self.adapter, "wire_transfer", "00")
        assert "GATEWAY_INVALID_CARD_DATA" not in result.violations

    def test_case_insensitive_expired(self):
        result = _eval(self.adapter, "wire_transfer", "expired")
        assert "GATEWAY_INVALID_CARD_DATA" in result.violations


# ===========================================================================
# 6. gateway_system_error  (soft_hold)
# ===========================================================================

class TestGatewaySystemError:
    """Processor / network error codes → GATEWAY_SYSTEM_ERROR soft_hold."""

    def setup_method(self):
        self.adapter = _make_adapter("gateway_system_error.yaml")

    @pytest.mark.parametrize("code", [
        "91", "96", "502", "503", "504", "517",
        "TIMEOUT", "UNAVAILABLE", "SERVICE_ERROR", "PROCESSOR_DOWN",
        "NETWORK_ERROR", "GATEWAY_ERROR", "SYSTEM_FAULT", "RE_ENTER",
    ])
    def test_soft_holds_system_error_code(self, code: str):
        result = _eval(self.adapter, "wire_transfer", code)
        assert "GATEWAY_SYSTEM_ERROR" in result.violations
        assert result.approved is False

    def test_passes_approved_code(self):
        result = _eval(self.adapter, "wire_transfer", "00")
        assert "GATEWAY_SYSTEM_ERROR" not in result.violations

    def test_passes_fraud_code(self):
        result = _eval(self.adapter, "wire_transfer", "41")
        assert "GATEWAY_SYSTEM_ERROR" not in result.violations

    def test_does_not_apply_to_loan_decision(self):
        result = _eval(self.adapter, "loan_decision", "91")
        assert "GATEWAY_SYSTEM_ERROR" not in result.violations


# ===========================================================================
# 7. Cross-rule: multiple gateway rules loaded together
# ===========================================================================

class TestGatewayRulesCombined:
    """All gateway rules loaded simultaneously — verify correct isolation."""

    def setup_method(self):
        self.adapter = _make_adapter(
            "gateway_fraud_decline.yaml",
            "gateway_card_restriction.yaml",
            "gateway_limit_exceeded.yaml",
            "gateway_insufficient_funds.yaml",
            "gateway_invalid_data.yaml",
            "gateway_system_error.yaml",
        )

    def test_fraud_code_only_triggers_fraud_rule(self):
        result = _eval(self.adapter, "wire_transfer", "41")
        assert "GATEWAY_FRAUD_DECLINE" in result.violations
        assert "GATEWAY_CARD_RESTRICTED" not in result.violations
        assert "GATEWAY_LIMIT_EXCEEDED" not in result.violations

    def test_nsf_code_only_triggers_nsf_rule(self):
        result = _eval(self.adapter, "wire_transfer", "51")
        assert "GATEWAY_INSUFFICIENT_FUNDS" in result.violations
        assert "GATEWAY_FRAUD_DECLINE" not in result.violations
        assert "GATEWAY_CARD_RESTRICTED" not in result.violations

    def test_system_error_code_only_triggers_system_rule(self):
        result = _eval(self.adapter, "wire_transfer", "503")
        assert "GATEWAY_SYSTEM_ERROR" in result.violations
        assert "GATEWAY_FRAUD_DECLINE" not in result.violations

    def test_invalid_data_code_only_triggers_invalid_rule(self):
        result = _eval(self.adapter, "wire_transfer", "54")
        assert "GATEWAY_INVALID_CARD_DATA" in result.violations
        assert "GATEWAY_FRAUD_DECLINE" not in result.violations

    def test_approved_code_triggers_nothing(self):
        result = _eval(self.adapter, "wire_transfer", "00")
        assert result.violations == []
        assert result.approved is True

    def test_unknown_code_triggers_nothing(self):
        result = _eval(self.adapter, "wire_transfer", "ZZZ_UNKNOWN")
        assert result.violations == []
        assert result.approved is True


# ===========================================================================
# 8. /validate/gateway-response endpoint integration
# (uses the shared async_client fixture from conftest.py — full rules loaded)
# All payloads include the required KYC / compliance fields so only the
# gateway rule under test fires.
# ===========================================================================

# Minimal complete payload — satisfies KYC, 3130, 3280, 5122, 6710, etc.
_BASE_PARAMS = {
    "customer_id": "CUST-GW-001",
    "account_id": "ACC-GW-001",
    "recipient_id": "LEGIT-BANK",
    "amount": 5000,
    "compliance_certification_year": "2026",
    "private_transaction_notice_ref": "PVT-001",
    "finra_filing_ref": "FINRA-PP-001",
    "trace_reporting_ref": "TRACE-001",
}


@pytest.mark.asyncio
async def test_endpoint_fraud_code_returns_hard_block(async_client):
    resp = await async_client.post("/validate/gateway-response", json={
        "action_type": "wire_transfer",
        "gateway_response_code": "FRAUD",
        "agent_id": "registered-agent-001",
        "parameters": _BASE_PARAMS,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["outcome"] == "hard_block"
    assert "GATEWAY_FRAUD_DECLINE" in data["violation_codes"]
    assert data["escalate_to_compliance"] is True
    assert data["sar_review_required"] is True
    assert data["retry_permitted"] is False


@pytest.mark.asyncio
async def test_endpoint_system_error_permits_retry(async_client):
    resp = await async_client.post("/validate/gateway-response", json={
        "action_type": "wire_transfer",
        "gateway_response_code": "TIMEOUT",
        "agent_id": "registered-agent-001",
        "parameters": _BASE_PARAMS,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "GATEWAY_SYSTEM_ERROR" in data["violation_codes"]
    assert data["retry_permitted"] is True
    assert data["sar_review_required"] is False
    assert data["escalate_to_compliance"] is True


@pytest.mark.asyncio
async def test_endpoint_invalid_data_flags_gateway_code(async_client):
    resp = await async_client.post("/validate/gateway-response", json={
        "action_type": "wire_transfer",
        "gateway_response_code": "EXPIRED",
        "agent_id": "registered-agent-001",
        "parameters": _BASE_PARAMS,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "GATEWAY_INVALID_CARD_DATA" in data["violation_codes"]
    assert data["retry_permitted"] is False
    assert data["sar_review_required"] is False


@pytest.mark.asyncio
async def test_endpoint_approved_code_no_gateway_violations(async_client):
    resp = await async_client.post("/validate/gateway-response", json={
        "action_type": "wire_transfer",
        "gateway_response_code": "00",
        "agent_id": "registered-agent-001",
        "parameters": _BASE_PARAMS,
    })
    assert resp.status_code == 200
    data = resp.json()
    # No gateway violations — code "00" matches no gateway rule
    gateway_codes = {c for c in data["violation_codes"] if c.startswith("GATEWAY_")}
    assert gateway_codes == set()
    assert data["retry_permitted"] is False
    assert data["sar_review_required"] is False


@pytest.mark.asyncio
async def test_endpoint_nsf_triggers_escalation(async_client):
    resp = await async_client.post("/validate/gateway-response", json={
        "action_type": "wire_transfer",
        "gateway_response_code": "NSF",
        "agent_id": "registered-agent-001",
        "parameters": _BASE_PARAMS,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "GATEWAY_INSUFFICIENT_FUNDS" in data["violation_codes"]
    assert data["escalate_to_compliance"] is True
    assert data["sar_review_required"] is True


@pytest.mark.asyncio
async def test_endpoint_returns_audit_entry_id(async_client):
    """Verify that every gateway response call is written to the audit log."""
    resp = await async_client.post("/validate/gateway-response", json={
        "action_type": "wire_transfer",
        "gateway_response_code": "BLOCKED",
        "agent_id": "registered-agent-001",
        "parameters": _BASE_PARAMS,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["audit_entry_id"] != ""
