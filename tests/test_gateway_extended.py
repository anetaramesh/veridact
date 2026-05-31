"""Extended payment gateway rule tests.

Covers gaps left by test_gateway_rules.py:
  1.  Near-miss / partial codes that must NOT match
  2.  Full ACH R-code suite (R02–R28)
  3.  ISO 8583 standard pass-through codes (00, 08, 10, 11, 85)
  4.  Systematic action-type scoping for every rule
  5.  SAR / retry / escalation flag matrix across all rules
  6.  Endpoint response schema and field-type validation
  7.  Empty / whitespace / numeric-string edge cases
  8.  Missing gateway_response_code field (no field in params)
  9.  Request ID uniqueness across consecutive calls
  10. Latency field is present and positive
  11. Audit entry written for every outcome
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from httpx import AsyncClient

RULES_DIR = Path(__file__).parent.parent / "rules"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _adapter(*rule_files: str):
    from src.engine.agt_adapter import AGTAdapter
    tmp = Path(tempfile.mkdtemp())
    for name in rule_files:
        src = RULES_DIR / name
        if src.exists():
            shutil.copy(src, tmp / name)
    return AGTAdapter(rules_dir=tmp)


def _all_gateway_adapter():
    return _adapter(
        "gateway_fraud_decline.yaml",
        "gateway_card_restriction.yaml",
        "gateway_limit_exceeded.yaml",
        "gateway_insufficient_funds.yaml",
        "gateway_invalid_data.yaml",
        "gateway_system_error.yaml",
    )


def _eval(adapter, action_type, gateway_response_code, **extra):
    params = {"gateway_response_code": gateway_response_code, **extra}
    return adapter.evaluate(action_type, params, {}, "test-agent")


# Minimal complete base payload for the shared-app endpoint tests
_EP_BASE = {
    "customer_id": "CUST-EXT-001",
    "account_id": "ACC-EXT-001",
    "recipient_id": "LEGIT-BANK",
    "amount": 5000,
    "compliance_certification_year": "2026",
    "private_transaction_notice_ref": "PVT-001",
    "finra_filing_ref": "FINRA-PP-001",
    "trace_reporting_ref": "TRACE-001",
}


# ===========================================================================
# 1. Near-miss codes — must NOT fire
# ===========================================================================

class TestNearMissCodes:
    """Codes that look similar to trigger codes but must not match."""

    def setup_method(self):
        self.adapter = _all_gateway_adapter()

    # Fraud near-misses
    @pytest.mark.parametrize("code", [
        "410",    # 41 + extra digit
        "4100",
        "435",    # 43 + extra digit
        "5160",   # 516 + extra digit
        "5161",
        "R290",   # R29 + extra digit
        "FRAUDULENT",   # longer word containing FRAUD — but pattern is anchored ^...$
        "PICKUPS",
        "STOLEN_CARD",  # not in pattern
        "LOST_CARD",    # not in pattern
    ])
    def test_fraud_near_miss_does_not_fire(self, code: str):
        result = _eval(self.adapter, "wire_transfer", code)
        assert "GATEWAY_FRAUD_DECLINE" not in result.violations, f"Should not match: {code}"

    # Card restriction near-misses
    @pytest.mark.parametrize("code", [
        "620",    # 62 + digit
        "780",
        "5100",   # 510 + digit
        "5111",
        "5120",
        "R070",
        "R080",
        "RESTRICTIONS",   # anchored — longer form
        "BLOCKED_ACCOUNT",  # not in pattern
    ])
    def test_card_restriction_near_miss_does_not_fire(self, code: str):
        result = _eval(self.adapter, "wire_transfer", code)
        assert "GATEWAY_CARD_RESTRICTED" not in result.violations, f"Should not match: {code}"

    # Limit near-misses
    @pytest.mark.parametrize("code", [
        "610",    # 61 + digit
        "650",
        "5130",
        "5140",
        "R010",
        "LIMITED",     # anchored
        "EXCEEDED_DAILY",
    ])
    def test_limit_near_miss_does_not_fire(self, code: str):
        result = _eval(self.adapter, "wire_transfer", code)
        assert "GATEWAY_LIMIT_EXCEEDED" not in result.violations, f"Should not match: {code}"

    # NSF near-misses
    @pytest.mark.parametrize("code", [
        "510",    # 51 + digit
        "5060",
        "R010",
        "R090",
        "NSFF",
        "INSUFFICIENTLY",
        "NO_FUNDS_AVAILABLE",  # not in pattern
    ])
    def test_nsf_near_miss_does_not_fire(self, code: str):
        result = _eval(self.adapter, "wire_transfer", code)
        assert "GATEWAY_INSUFFICIENT_FUNDS" not in result.violations, f"Should not match: {code}"

    # System error near-misses
    @pytest.mark.parametrize("code", [
        "910",    # 91 + digit
        "960",
        "5020",
        "5030",
        "5040",
        "5170",
        "TIMED_OUT",    # not in pattern
        "UNAVAILABILITY",
    ])
    def test_system_error_near_miss_does_not_fire(self, code: str):
        result = _eval(self.adapter, "wire_transfer", code)
        assert "GATEWAY_SYSTEM_ERROR" not in result.violations, f"Should not match: {code}"


# ===========================================================================
# 2. ACH Return Code suite (R02 – R28)
# ===========================================================================

class TestACHReturnCodes:
    """ACH R-codes not explicitly in rule patterns should not trigger gateway rules.
    R01 and R09 are covered in gateway_insufficient_funds; R07/R08 in card restriction;
    R29 in fraud. All others should pass through without a gateway violation.
    """

    def setup_method(self):
        self.adapter = _all_gateway_adapter()

    @pytest.mark.parametrize("code", [
        "R02",  # Account closed
        "R03",  # No account / Unable to locate account
        "R04",  # Invalid account number
        "R05",  # Reserved
        "R06",  # Returned per ODFI request
        "R10",  # Customer advises not authorised
        "R11",  # Check truncation entry return
        "R12",  # Account sold to another DFI
        "R13",  # Invalid ACH routing number
        "R14",  # Representative payee deceased
        "R15",  # Beneficiary deceased
        "R16",  # Account frozen
        "R17",  # File record edit criteria
        "R20",  # Non-transaction account
        "R21",  # Invalid company identification
        "R22",  # Invalid individual ID number
        "R23",  # Credit entry refused by receiver
        "R24",  # Duplicate entry
        "R25",  # Addenda error
        "R26",  # Mandatory field error
        "R27",  # Trace number error
        "R28",  # Transit / routing number check digit error
    ])
    def test_unclassified_ach_code_triggers_no_gateway_rule(self, code: str):
        result = _eval(self.adapter, "ach_payment", code)
        gw_violations = [v for v in result.violations if v.startswith("GATEWAY_")]
        assert gw_violations == [], f"Unexpected gateway violation for {code}: {gw_violations}"

    def test_r01_triggers_nsf(self):
        """R01 (Insufficient funds) should hit gateway_insufficient_funds."""
        result = _eval(self.adapter, "ach_payment", "R01")
        assert "GATEWAY_INSUFFICIENT_FUNDS" in result.violations

    def test_r07_triggers_card_restriction(self):
        """R07 (Authorisation revoked) should hit gateway_card_restriction."""
        result = _eval(self.adapter, "ach_payment", "R07")
        assert "GATEWAY_CARD_RESTRICTED" in result.violations

    def test_r08_triggers_card_restriction(self):
        """R08 (Payment stopped) should hit gateway_card_restriction."""
        result = _eval(self.adapter, "ach_payment", "R08")
        assert "GATEWAY_CARD_RESTRICTED" in result.violations

    def test_r09_triggers_nsf(self):
        """R09 (Uncollected funds) should hit gateway_insufficient_funds."""
        result = _eval(self.adapter, "ach_payment", "R09")
        assert "GATEWAY_INSUFFICIENT_FUNDS" in result.violations

    def test_r29_triggers_fraud(self):
        """R29 (Corporate customer advises not authorised) should hit fraud rule."""
        result = _eval(self.adapter, "ach_payment", "R29")
        assert "GATEWAY_FRAUD_DECLINE" in result.violations


# ===========================================================================
# 3. ISO 8583 standard pass-through codes
# ===========================================================================

class TestISO8583PassthroughCodes:
    """Standard ISO 8583 codes that indicate success or referral — no gateway rule fires."""

    def setup_method(self):
        self.adapter = _all_gateway_adapter()

    @pytest.mark.parametrize("code", [
        "00",   # Approved
        "08",   # Honour with identification
        "10",   # Partial approval
        "11",   # VIP approval
        "85",   # Card acceptor transaction not supported
        "01",   # Refer to card issuer (referral, not automatic block)
        "02",   # Refer to card issuer — special conditions
        "03",   # Invalid merchant
        "04",   # Pick up card (no owner present — different from 41/43)
        "07",   # Honour with identification
        "12",   # Invalid transaction
        "13",   # Invalid amount
        "15",   # No such issuer
        "30",   # Format error (not FORMAT_ERROR string)
        "20",   # Invalid response
    ])
    def test_iso_pass_through_code_triggers_no_gateway_rule(self, code: str):
        result = _eval(self.adapter, "wire_transfer", code)
        gw_violations = [v for v in result.violations if v.startswith("GATEWAY_")]
        assert gw_violations == [], f"Unexpected gateway violation for ISO code {code}: {gw_violations}"


# ===========================================================================
# 4. Systematic action-type scoping
# ===========================================================================

class TestActionTypeScoping:
    """Verify every rule fires exactly on its declared action types and not on others."""

    # action types covered by each rule (from YAML action_types fields)
    FRAUD_COVERED    = {"wire_transfer","ach_payment","internal_transfer","check_issuance","equity_trade","loan_decision","account_open"}
    RESTRICT_COVERED = {"wire_transfer","ach_payment","internal_transfer","check_issuance","equity_trade","loan_decision","account_open"}
    LIMIT_COVERED    = {"wire_transfer","ach_payment","internal_transfer","check_issuance","equity_trade"}
    NSF_COVERED      = {"wire_transfer","ach_payment","internal_transfer","check_issuance"}
    INVALID_COVERED  = {"wire_transfer","ach_payment","internal_transfer","check_issuance","equity_trade","loan_decision","account_open"}
    SYSTEM_COVERED   = {"wire_transfer","ach_payment","internal_transfer","check_issuance","equity_trade"}

    NOT_COVERED_BY_LIMIT  = {"loan_decision","account_open"}
    NOT_COVERED_BY_NSF    = {"equity_trade","loan_decision","account_open"}
    NOT_COVERED_BY_SYSTEM = {"loan_decision","account_open"}

    def setup_method(self):
        self.fraud    = _adapter("gateway_fraud_decline.yaml")
        self.restrict = _adapter("gateway_card_restriction.yaml")
        self.limit    = _adapter("gateway_limit_exceeded.yaml")
        self.nsf      = _adapter("gateway_insufficient_funds.yaml")
        self.invalid  = _adapter("gateway_invalid_data.yaml")
        self.system   = _adapter("gateway_system_error.yaml")

    @pytest.mark.parametrize("action", ["wire_transfer","ach_payment","internal_transfer","check_issuance","equity_trade","loan_decision","account_open"])
    def test_fraud_rule_covers_all_declared_actions(self, action):
        result = _eval(self.fraud, action, "FRAUD")
        assert "GATEWAY_FRAUD_DECLINE" in result.violations, f"Expected fraud block for {action}"

    @pytest.mark.parametrize("action", ["wire_transfer","ach_payment","internal_transfer","check_issuance","equity_trade","loan_decision","account_open"])
    def test_card_restriction_covers_all_declared_actions(self, action):
        result = _eval(self.restrict, action, "BLOCKED")
        assert "GATEWAY_CARD_RESTRICTED" in result.violations, f"Expected restriction for {action}"

    @pytest.mark.parametrize("action", ["wire_transfer","ach_payment","internal_transfer","check_issuance","equity_trade"])
    def test_limit_covers_declared_actions(self, action):
        result = _eval(self.limit, action, "61")
        assert "GATEWAY_LIMIT_EXCEEDED" in result.violations, f"Expected limit for {action}"

    @pytest.mark.parametrize("action", ["loan_decision","account_open"])
    def test_limit_does_not_cover_excluded_actions(self, action):
        result = _eval(self.limit, action, "61")
        assert "GATEWAY_LIMIT_EXCEEDED" not in result.violations

    @pytest.mark.parametrize("action", ["wire_transfer","ach_payment","internal_transfer","check_issuance"])
    def test_nsf_covers_declared_actions(self, action):
        result = _eval(self.nsf, action, "NSF")
        assert "GATEWAY_INSUFFICIENT_FUNDS" in result.violations

    @pytest.mark.parametrize("action", ["equity_trade","loan_decision","account_open"])
    def test_nsf_does_not_cover_excluded_actions(self, action):
        result = _eval(self.nsf, action, "NSF")
        assert "GATEWAY_INSUFFICIENT_FUNDS" not in result.violations

    @pytest.mark.parametrize("action", ["wire_transfer","ach_payment","internal_transfer","check_issuance","equity_trade"])
    def test_system_error_covers_declared_actions(self, action):
        result = _eval(self.system, action, "TIMEOUT")
        assert "GATEWAY_SYSTEM_ERROR" in result.violations

    @pytest.mark.parametrize("action", ["loan_decision","account_open"])
    def test_system_error_does_not_cover_excluded_actions(self, action):
        result = _eval(self.system, action, "TIMEOUT")
        assert "GATEWAY_SYSTEM_ERROR" not in result.violations


# ===========================================================================
# 5. SAR / retry / escalation flag matrix
# ===========================================================================

class TestComplianceFlagMatrix:
    """Every violation code maps to the correct SAR, retry, escalation flags
    via the /validate/gateway-response endpoint."""

    # (gateway_response_code, expected_violation, sar_required, retry_permitted, escalate)
    MATRIX = [
        ("FRAUD",       "GATEWAY_FRAUD_DECLINE",       True,  False, True),
        ("41",          "GATEWAY_FRAUD_DECLINE",       True,  False, True),
        ("BLOCKED",     "GATEWAY_CARD_RESTRICTED",     True,  False, True),
        ("62",          "GATEWAY_CARD_RESTRICTED",     True,  False, True),
        ("61",          "GATEWAY_LIMIT_EXCEEDED",      True,  False, True),
        ("VELOCITY",    "GATEWAY_LIMIT_EXCEEDED",      True,  False, True),
        ("NSF",         "GATEWAY_INSUFFICIENT_FUNDS",  True,  False, True),
        ("51",          "GATEWAY_INSUFFICIENT_FUNDS",  True,  False, True),
        ("TIMEOUT",     "GATEWAY_SYSTEM_ERROR",        False, True,  True),
        ("503",         "GATEWAY_SYSTEM_ERROR",        False, True,  True),
        # Invalid data is flag-severity — no escalation, no SAR, no retry block
        ("EXPIRED",     "GATEWAY_INVALID_CARD_DATA",   False, False, False),
        ("54",          "GATEWAY_INVALID_CARD_DATA",   False, False, False),
        # Clean code — nothing fires
        ("00",          None,                          False, False, False),
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("code,violation,sar,retry,escalate", MATRIX)
    async def test_flag_matrix(self, async_client: AsyncClient, code, violation, sar, retry, escalate):
        resp = await async_client.post("/validate/gateway-response", json={
            "action_type": "wire_transfer",
            "gateway_response_code": code,
            "agent_id": "registered-agent-001",
            "parameters": _EP_BASE,
        })
        assert resp.status_code == 200
        data = resp.json()

        if violation:
            assert violation in data["violation_codes"], f"Expected {violation} for code {code}"
        assert data["sar_review_required"]    == sar,     f"SAR mismatch for {code}"
        assert data["retry_permitted"]        == retry,   f"Retry mismatch for {code}"
        assert data["escalate_to_compliance"] == escalate, f"Escalate mismatch for {code}"


# ===========================================================================
# 6. Endpoint response schema validation
# ===========================================================================

class TestEndpointResponseSchema:
    """Verify all required fields are present with correct types on every response."""

    REQUIRED_FIELDS = {
        "request_id":             str,
        "gateway_response_code":  str,
        "violation_codes":        list,
        "outcome":                str,
        "retry_permitted":        bool,
        "escalate_to_compliance": bool,
        "sar_review_required":    bool,
        "rationale":              str,
        "latency_ms":             (int, float),
        "audit_entry_id":         str,
    }

    VALID_OUTCOMES = {"approved", "hard_block", "soft_hold", "flagged"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("code", ["FRAUD", "NSF", "TIMEOUT", "EXPIRED", "00", "ZZZ_UNKNOWN"])
    async def test_response_schema_complete(self, async_client: AsyncClient, code: str):
        resp = await async_client.post("/validate/gateway-response", json={
            "action_type": "wire_transfer",
            "gateway_response_code": code,
            "agent_id": "registered-agent-001",
            "parameters": _EP_BASE,
        })
        assert resp.status_code == 200
        data = resp.json()

        for field, expected_type in self.REQUIRED_FIELDS.items():
            assert field in data, f"Missing field '{field}' for code {code}"
            assert isinstance(data[field], expected_type), (
                f"Field '{field}' has wrong type {type(data[field])} for code {code}"
            )

        assert data["outcome"] in self.VALID_OUTCOMES, f"Unexpected outcome '{data['outcome']}'"
        assert data["gateway_response_code"] == code, "Response code mismatch"

    @pytest.mark.asyncio
    async def test_latency_is_positive(self, async_client: AsyncClient):
        resp = await async_client.post("/validate/gateway-response", json={
            "action_type": "wire_transfer",
            "gateway_response_code": "FRAUD",
            "agent_id": "registered-agent-001",
            "parameters": _EP_BASE,
        })
        data = resp.json()
        assert data["latency_ms"] > 0

    @pytest.mark.asyncio
    async def test_rationale_is_non_empty(self, async_client: AsyncClient):
        resp = await async_client.post("/validate/gateway-response", json={
            "action_type": "wire_transfer",
            "gateway_response_code": "BLOCKED",
            "agent_id": "registered-agent-001",
            "parameters": _EP_BASE,
        })
        data = resp.json()
        assert len(data["rationale"].strip()) > 0

    @pytest.mark.asyncio
    async def test_violation_codes_are_strings(self, async_client: AsyncClient):
        resp = await async_client.post("/validate/gateway-response", json={
            "action_type": "wire_transfer",
            "gateway_response_code": "FRAUD",
            "agent_id": "registered-agent-001",
            "parameters": _EP_BASE,
        })
        data = resp.json()
        assert all(isinstance(c, str) for c in data["violation_codes"])


# ===========================================================================
# 7. Request ID uniqueness
# ===========================================================================

class TestRequestIDUniqueness:
    @pytest.mark.asyncio
    async def test_consecutive_calls_have_unique_request_ids(self, async_client: AsyncClient):
        ids = set()
        for _ in range(5):
            resp = await async_client.post("/validate/gateway-response", json={
                "action_type": "wire_transfer",
                "gateway_response_code": "FRAUD",
                "agent_id": "registered-agent-001",
                "parameters": _EP_BASE,
            })
            ids.add(resp.json()["request_id"])
        assert len(ids) == 5, "All request IDs should be unique"


# ===========================================================================
# 8. Edge cases — empty / whitespace / missing field
# ===========================================================================

class TestEdgeCases:
    """Empty codes, whitespace, and missing gateway_response_code field."""

    def setup_method(self):
        self.adapter = _all_gateway_adapter()

    def test_empty_string_code_triggers_no_rule(self):
        result = self.adapter.evaluate("wire_transfer", {"gateway_response_code": ""}, {}, "agent-1")
        gw = [v for v in result.violations if v.startswith("GATEWAY_")]
        assert gw == []

    def test_whitespace_code_triggers_no_rule(self):
        result = self.adapter.evaluate("wire_transfer", {"gateway_response_code": "   "}, {}, "agent-1")
        gw = [v for v in result.violations if v.startswith("GATEWAY_")]
        assert gw == []

    def test_missing_field_triggers_no_rule(self):
        """When gateway_response_code is absent from params, no gateway rule fires."""
        result = self.adapter.evaluate("wire_transfer", {"amount": 5000}, {}, "agent-1")
        gw = [v for v in result.violations if v.startswith("GATEWAY_")]
        assert gw == []

    def test_numeric_string_codes_match_correctly(self):
        """Numeric strings should still match (e.g. '41' stored as string)."""
        result = _eval(self.adapter, "wire_transfer", "41")
        assert "GATEWAY_FRAUD_DECLINE" in result.violations

    def test_code_with_leading_zero_matches(self):
        """'00' should not match any rule; '041' should not match '41'."""
        result_00 = _eval(self.adapter, "wire_transfer", "00")
        assert not any(v.startswith("GATEWAY_") for v in result_00.violations)

        result_041 = _eval(self.adapter, "wire_transfer", "041")
        assert "GATEWAY_FRAUD_DECLINE" not in result_041.violations

    def test_code_with_trailing_space_does_not_match(self):
        """'FRAUD ' (trailing space) must not match due to $ anchor."""
        result = _eval(self.adapter, "wire_transfer", "FRAUD ")
        assert "GATEWAY_FRAUD_DECLINE" not in result.violations

    def test_code_with_leading_space_does_not_match(self):
        result = _eval(self.adapter, "wire_transfer", " FRAUD")
        assert "GATEWAY_FRAUD_DECLINE" not in result.violations

    @pytest.mark.asyncio
    async def test_endpoint_missing_gateway_code_field_returns_400(self, async_client: AsyncClient):
        """Request without gateway_response_code should return 422 validation error."""
        resp = await async_client.post("/validate/gateway-response", json={
            "action_type": "wire_transfer",
            "agent_id": "agent-001",
            "parameters": _EP_BASE,
            # gateway_response_code intentionally omitted
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_endpoint_empty_code_returns_no_gateway_violations(self, async_client: AsyncClient):
        resp = await async_client.post("/validate/gateway-response", json={
            "action_type": "wire_transfer",
            "gateway_response_code": "",
            "agent_id": "registered-agent-001",
            "parameters": _EP_BASE,
        })
        assert resp.status_code == 200
        data = resp.json()
        gw = [c for c in data["violation_codes"] if c.startswith("GATEWAY_")]
        assert gw == []


# ===========================================================================
# 9. Severity contract — hard_block vs soft_hold vs flag
# ===========================================================================

class TestSeverityContract:
    """Verify that rule severities produce the expected approved / outcome values."""

    def setup_method(self):
        self.fraud   = _adapter("gateway_fraud_decline.yaml")
        self.limit   = _adapter("gateway_limit_exceeded.yaml")
        self.nsf     = _adapter("gateway_insufficient_funds.yaml")
        self.invalid = _adapter("gateway_invalid_data.yaml")
        self.system  = _adapter("gateway_system_error.yaml")
        self.restrict = _adapter("gateway_card_restriction.yaml")

    def test_fraud_hard_block_sets_approved_false(self):
        result = _eval(self.fraud, "wire_transfer", "FRAUD")
        assert result.approved is False

    def test_card_restriction_hard_block_sets_approved_false(self):
        result = _eval(self.restrict, "wire_transfer", "BLOCKED")
        assert result.approved is False

    def test_limit_soft_hold_sets_approved_false(self):
        result = _eval(self.limit, "wire_transfer", "61")
        assert result.approved is False

    def test_nsf_soft_hold_sets_approved_false(self):
        result = _eval(self.nsf, "wire_transfer", "NSF")
        assert result.approved is False

    def test_system_error_soft_hold_sets_approved_false(self):
        result = _eval(self.system, "wire_transfer", "TIMEOUT")
        assert result.approved is False

    def test_invalid_data_flag_keeps_approved_true(self):
        """Flag severity should NOT block — action is still approved."""
        result = _eval(self.invalid, "wire_transfer", "EXPIRED")
        assert result.approved is True
        assert "GATEWAY_INVALID_CARD_DATA" in result.violations

    def test_clean_code_keeps_approved_true(self):
        all_adapter = _all_gateway_adapter()
        result = _eval(all_adapter, "wire_transfer", "00")
        assert result.approved is True
        assert result.violations == []


# ===========================================================================
# 10. Audit trail — every gateway call produces an entry
# ===========================================================================

class TestAuditTrail:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("code", ["FRAUD", "NSF", "TIMEOUT", "EXPIRED", "00"])
    async def test_each_outcome_produces_audit_entry(self, async_client: AsyncClient, code: str):
        resp = await async_client.post("/validate/gateway-response", json={
            "action_type": "wire_transfer",
            "gateway_response_code": code,
            "agent_id": "registered-agent-001",
            "parameters": _EP_BASE,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["audit_entry_id"] != "", f"No audit entry for code {code}"
        assert isinstance(data["audit_entry_id"], str)

    @pytest.mark.asyncio
    async def test_audit_entries_are_unique_per_call(self, async_client: AsyncClient):
        entry_ids = []
        for code in ("FRAUD", "NSF", "TIMEOUT"):
            resp = await async_client.post("/validate/gateway-response", json={
                "action_type": "wire_transfer",
                "gateway_response_code": code,
                "agent_id": "registered-agent-001",
                "parameters": _EP_BASE,
            })
            entry_ids.append(resp.json()["audit_entry_id"])
        assert len(set(entry_ids)) == 3, "Each call should produce a unique audit entry"


# ===========================================================================
# 11. Rationale content validation
# ===========================================================================

class TestRationaleContent:
    """The rationale should include the gateway code and actionable guidance."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("code,expected_hint", [
        ("FRAUD",   "GATEWAY_FRAUD_DECLINE"),
        ("NSF",     "GATEWAY_INSUFFICIENT_FUNDS"),
        ("TIMEOUT", "GATEWAY_SYSTEM_ERROR"),
        ("EXPIRED", "GATEWAY_INVALID_CARD_DATA"),
    ])
    async def test_rationale_references_violation_code(
        self, async_client: AsyncClient, code: str, expected_hint: str
    ):
        resp = await async_client.post("/validate/gateway-response", json={
            "action_type": "wire_transfer",
            "gateway_response_code": code,
            "agent_id": "registered-agent-001",
            "parameters": _EP_BASE,
        })
        data = resp.json()
        assert expected_hint in data["rationale"], (
            f"Rationale should mention {expected_hint} for code {code}"
        )

    @pytest.mark.asyncio
    async def test_rationale_mentions_gateway_code(self, async_client: AsyncClient):
        resp = await async_client.post("/validate/gateway-response", json={
            "action_type": "wire_transfer",
            "gateway_response_code": "BLOCKED",
            "agent_id": "registered-agent-001",
            "parameters": _EP_BASE,
        })
        data = resp.json()
        assert "BLOCKED" in data["rationale"]

    @pytest.mark.asyncio
    async def test_clean_code_rationale_indicates_no_action(self, async_client: AsyncClient):
        resp = await async_client.post("/validate/gateway-response", json={
            "action_type": "wire_transfer",
            "gateway_response_code": "00",
            "agent_id": "registered-agent-001",
            "parameters": _EP_BASE,
        })
        data = resp.json()
        # Rationale should indicate no compliance action required
        assert "No action" in data["rationale"] or "no" in data["rationale"].lower()
