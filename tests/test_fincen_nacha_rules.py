"""Tests for FinCEN/BSA and Nacha compliance rule YAML files.

FinCEN / BSA rules:
  - fincen_ctr_threshold        (soft_hold: amount > $10,000)
  - fincen_structuring          (hard_block: structuring keywords in memo)
  - fincen_sar_trigger          (hard_block: SAR-trigger keywords in memo)
  - fincen_beneficial_ownership (hard_block: missing beneficial_owner_id etc.)
  - fincen_high_risk_jurisdiction (hard_block: sanctioned jurisdiction codes)

Nacha ACH rules:
  - nacha_same_day_ach_limit         (hard_block: amount > $1,000,000)
  - nacha_return_rate_admin          (soft_hold: admin return rate > 3.0%)
  - nacha_return_rate_unauthorized   (hard_block: unauthorized return rate > 0.5%)
  - nacha_web_debit_authorization    (hard_block: missing web_authorization_ref)
  - nacha_micro_entry_verification   (hard_block: missing micro_entry_registration_ref)
  - nacha_tpsp_authorization         (hard_block: missing tpsp_registration_ref)
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


def _eval(adapter, action_type: str, params: dict, agent_id: str = "agent-test"):
    return adapter.evaluate(action_type, params, {}, agent_id)


# ===========================================================================
# FinCEN / BSA — CTR Threshold
# ===========================================================================

class TestFinCENCTRThreshold:
    """Amount > $10,000 triggers CTR soft hold on cash-equivalent transfers."""

    def setup_method(self):
        self.adapter = _adapter("fincen_ctr_threshold.yaml")

    def test_soft_holds_above_10k(self):
        result = _eval(self.adapter, "wire_transfer", {"amount": 10001})
        assert "FINCEN_CTR_REQUIRED" in result.violations
        assert result.approved is False

    def test_passes_at_exactly_10k(self):
        result = _eval(self.adapter, "wire_transfer", {"amount": 10000})
        assert "FINCEN_CTR_REQUIRED" not in result.violations

    def test_passes_below_10k(self):
        result = _eval(self.adapter, "wire_transfer", {"amount": 9999})
        assert result.approved is True

    @pytest.mark.parametrize("amount", [10001, 50000, 100000, 1_000_000, 9_999_999])
    def test_all_large_amounts_trigger(self, amount: int):
        result = _eval(self.adapter, "wire_transfer", {"amount": amount})
        assert "FINCEN_CTR_REQUIRED" in result.violations

    @pytest.mark.parametrize("action", ["wire_transfer", "ach_payment", "check_issuance", "internal_transfer"])
    def test_applies_to_covered_action_types(self, action: str):
        result = _eval(self.adapter, action, {"amount": 15000})
        assert "FINCEN_CTR_REQUIRED" in result.violations, f"Expected CTR for {action}"

    def test_does_not_apply_to_equity_trade(self):
        result = _eval(self.adapter, "equity_trade", {"amount": 500000})
        assert "FINCEN_CTR_REQUIRED" not in result.violations

    def test_does_not_apply_to_loan_decision(self):
        result = _eval(self.adapter, "loan_decision", {"amount": 500000})
        assert "FINCEN_CTR_REQUIRED" not in result.violations

    def test_boundary_9999_passes(self):
        result = _eval(self.adapter, "ach_payment", {"amount": 9999})
        assert "FINCEN_CTR_REQUIRED" not in result.violations

    def test_boundary_10001_triggers(self):
        result = _eval(self.adapter, "ach_payment", {"amount": 10001})
        assert "FINCEN_CTR_REQUIRED" in result.violations


# ===========================================================================
# FinCEN / BSA — Structuring Detection
# ===========================================================================

class TestFinCENStructuring:
    """Structuring / smurfing keywords in memo → hard_block."""

    def setup_method(self):
        self.adapter = _adapter("fincen_structuring.yaml")

    @pytest.mark.parametrize("memo", [
        "structuring the payment",
        "smurfing operation",
        "smurf the deposits",
        "break up transaction to avoid report",
        "split deposit below limit",
        "avoid CTR reporting",
        "evade CTR requirement",
        "under ten thousand each",
        "just below the limit",
        "9500 transfer",
        "9800 wire",
        "9,900 payment",
    ])
    def test_blocks_structuring_memo(self, memo: str):
        result = _eval(self.adapter, "wire_transfer", {"memo": memo, "amount": 9500})
        assert "FINCEN_STRUCTURING_DETECTED" in result.violations
        assert result.approved is False

    def test_passes_clean_memo(self):
        result = _eval(self.adapter, "wire_transfer", {"memo": "monthly payroll transfer", "amount": 9500})
        assert "FINCEN_STRUCTURING_DETECTED" not in result.violations

    def test_case_insensitive_structuring(self):
        result = _eval(self.adapter, "wire_transfer", {"memo": "STRUCTURING PAYMENT"})
        assert "FINCEN_STRUCTURING_DETECTED" in result.violations

    def test_passes_empty_memo(self):
        result = _eval(self.adapter, "wire_transfer", {"memo": ""})
        assert "FINCEN_STRUCTURING_DETECTED" not in result.violations

    def test_passes_missing_memo_field(self):
        result = _eval(self.adapter, "wire_transfer", {"amount": 9000})
        assert "FINCEN_STRUCTURING_DETECTED" not in result.violations

    @pytest.mark.parametrize("action", ["wire_transfer", "ach_payment", "check_issuance", "internal_transfer"])
    def test_applies_to_covered_action_types(self, action: str):
        result = _eval(self.adapter, action, {"memo": "structuring the transfer"})
        assert "FINCEN_STRUCTURING_DETECTED" in result.violations, f"Expected block for {action}"


# ===========================================================================
# FinCEN / BSA — SAR Trigger
# ===========================================================================

class TestFinCENSARTrigger:
    """SAR-trigger keywords in memo → hard_block."""

    def setup_method(self):
        self.adapter = _adapter("fincen_sar_trigger.yaml")

    @pytest.mark.parametrize("memo", [
        "money laundering proceeds",
        "terror financing operation",
        "illicit funds transfer",
        "criminal proceeds payment",
        "drug proceeds wire",
        "narco cartel payment",
        "tax evasion fund movement",
        "offshore hide the money",
        "undeclared funds transfer",
        "black market proceeds",
        "bribery payment",
        "kickback arrangement",
        "embezzlement proceeds",
        "ponzi scheme",
        "fraud proceeds wire",
    ])
    def test_blocks_sar_trigger_memo(self, memo: str):
        result = _eval(self.adapter, "wire_transfer", {"memo": memo})
        assert "FINCEN_SAR_TRIGGER" in result.violations
        assert result.approved is False

    def test_passes_clean_memo(self):
        result = _eval(self.adapter, "wire_transfer", {"memo": "vendor invoice payment Q2 2026"})
        assert "FINCEN_SAR_TRIGGER" not in result.violations

    def test_case_insensitive_launder(self):
        result = _eval(self.adapter, "wire_transfer", {"memo": "MONEY LAUNDERING"})
        assert "FINCEN_SAR_TRIGGER" in result.violations

    @pytest.mark.parametrize("action", ["wire_transfer", "ach_payment", "equity_trade", "loan_decision"])
    def test_applies_across_action_types(self, action: str):
        result = _eval(self.adapter, action, {"memo": "illicit fund transfer"})
        assert "FINCEN_SAR_TRIGGER" in result.violations, f"Expected SAR trigger for {action}"


# ===========================================================================
# FinCEN / BSA — Beneficial Ownership
# ===========================================================================

class TestFinCENBeneficialOwnership:
    """Missing beneficial ownership fields → hard_block on account_open / wire_transfer."""

    def setup_method(self):
        self.adapter = _adapter("fincen_beneficial_ownership.yaml")

    _FULL = {
        "customer_id":       "CUST-001",
        "account_id":        "ACC-001",
        "beneficial_owner_id":  "BO-001",
        "beneficial_owner_dob": "1970-03-15",
        "control_prong_name":   "Jane Smith",
    }

    def test_passes_with_all_required_fields(self):
        result = _eval(self.adapter, "account_open", self._FULL)
        assert "FINCEN_BENEFICIAL_OWNERSHIP_MISSING" not in result.violations

    @pytest.mark.parametrize("missing_field", [
        "beneficial_owner_id",
        "beneficial_owner_dob",
        "control_prong_name",
        "customer_id",
        "account_id",
    ])
    def test_blocks_when_field_missing(self, missing_field: str):
        params = {k: v for k, v in self._FULL.items() if k != missing_field}
        result = _eval(self.adapter, "account_open", params)
        assert "FINCEN_BENEFICIAL_OWNERSHIP_MISSING" in result.violations

    def test_applies_to_wire_transfer(self):
        params = {k: v for k, v in self._FULL.items() if k != "beneficial_owner_id"}
        result = _eval(self.adapter, "wire_transfer", params)
        assert "FINCEN_BENEFICIAL_OWNERSHIP_MISSING" in result.violations

    def test_does_not_apply_to_equity_trade(self):
        result = _eval(self.adapter, "equity_trade", {"customer_id": "C1", "account_id": "A1"})
        assert "FINCEN_BENEFICIAL_OWNERSHIP_MISSING" not in result.violations

    def test_empty_field_triggers_block(self):
        params = {**self._FULL, "beneficial_owner_id": ""}
        result = _eval(self.adapter, "account_open", params)
        assert "FINCEN_BENEFICIAL_OWNERSHIP_MISSING" in result.violations


# ===========================================================================
# FinCEN / BSA — High-Risk Jurisdiction
# ===========================================================================

class TestFinCENHighRiskJurisdiction:
    """Sanctioned / FATF-listed jurisdiction codes → hard_block."""

    def setup_method(self):
        self.adapter = _adapter("fincen_high_risk_jurisdiction.yaml")

    @pytest.mark.parametrize("code", [
        "IR", "IRN",    # Iran
        "KP", "PRK",    # North Korea
        "CU", "CUB",    # Cuba
        "SY", "SYR",    # Syria
        "BY",           # Belarus
        "MM",           # Myanmar
        "SD",           # Sudan
        "VE",           # Venezuela
        "FATF_BLACK",
        "FATF_GREY",
    ])
    def test_blocks_sanctioned_jurisdiction(self, code: str):
        result = _eval(self.adapter, "wire_transfer", {"jurisdiction_code": code})
        assert "FINCEN_HIGH_RISK_JURISDICTION" in result.violations
        assert result.approved is False

    @pytest.mark.parametrize("code", ["US", "GB", "DE", "JP", "CA", "AU", "FR"])
    def test_passes_low_risk_jurisdiction(self, code: str):
        result = _eval(self.adapter, "wire_transfer", {"jurisdiction_code": code})
        assert "FINCEN_HIGH_RISK_JURISDICTION" not in result.violations

    def test_applies_to_ach_payment(self):
        result = _eval(self.adapter, "ach_payment", {"jurisdiction_code": "KP"})
        assert "FINCEN_HIGH_RISK_JURISDICTION" in result.violations

    def test_does_not_apply_to_equity_trade(self):
        result = _eval(self.adapter, "equity_trade", {"jurisdiction_code": "IR"})
        assert "FINCEN_HIGH_RISK_JURISDICTION" not in result.violations

    def test_missing_jurisdiction_field_passes(self):
        result = _eval(self.adapter, "wire_transfer", {"amount": 5000})
        assert "FINCEN_HIGH_RISK_JURISDICTION" not in result.violations


# ===========================================================================
# Nacha — Same-Day ACH Limit
# ===========================================================================

class TestNachaSameDayACHLimit:
    """Amount > $1,000,000 → hard_block on ach_payment."""

    def setup_method(self):
        self.adapter = _adapter("nacha_same_day_ach_limit.yaml")

    def test_blocks_above_1m(self):
        result = _eval(self.adapter, "ach_payment", {"amount": 1_000_001})
        assert "NACHA_SAME_DAY_LIMIT_EXCEEDED" in result.violations
        assert result.approved is False

    def test_passes_at_exactly_1m(self):
        result = _eval(self.adapter, "ach_payment", {"amount": 1_000_000})
        assert "NACHA_SAME_DAY_LIMIT_EXCEEDED" not in result.violations

    def test_passes_below_1m(self):
        result = _eval(self.adapter, "ach_payment", {"amount": 999_999})
        assert result.approved is True

    @pytest.mark.parametrize("amount", [1_000_001, 5_000_000, 10_000_000])
    def test_all_overlimit_amounts_blocked(self, amount: int):
        result = _eval(self.adapter, "ach_payment", {"amount": amount})
        assert "NACHA_SAME_DAY_LIMIT_EXCEEDED" in result.violations

    def test_does_not_apply_to_wire_transfer(self):
        result = _eval(self.adapter, "wire_transfer", {"amount": 2_000_000})
        assert "NACHA_SAME_DAY_LIMIT_EXCEEDED" not in result.violations

    def test_does_not_apply_to_equity_trade(self):
        result = _eval(self.adapter, "equity_trade", {"amount": 5_000_000})
        assert "NACHA_SAME_DAY_LIMIT_EXCEEDED" not in result.violations


# ===========================================================================
# Nacha — Admin Return Rate Threshold
# ===========================================================================

class TestNachaAdminReturnRate:
    """admin_return_rate_pct > 3.0% → soft_hold."""

    def setup_method(self):
        self.adapter = _adapter("nacha_return_rate_admin.yaml")

    def test_soft_holds_above_3pct(self):
        result = _eval(self.adapter, "ach_payment", {"admin_return_rate_pct": 3.1})
        assert "NACHA_ADMIN_RETURN_RATE_EXCEEDED" in result.violations
        assert result.approved is False

    def test_passes_at_exactly_3pct(self):
        result = _eval(self.adapter, "ach_payment", {"admin_return_rate_pct": 3.0})
        assert "NACHA_ADMIN_RETURN_RATE_EXCEEDED" not in result.violations

    def test_passes_below_3pct(self):
        result = _eval(self.adapter, "ach_payment", {"admin_return_rate_pct": 2.9})
        assert result.approved is True

    @pytest.mark.parametrize("rate", [3.01, 5.0, 10.0, 50.0])
    def test_all_high_rates_trigger(self, rate: float):
        result = _eval(self.adapter, "ach_payment", {"admin_return_rate_pct": rate})
        assert "NACHA_ADMIN_RETURN_RATE_EXCEEDED" in result.violations

    def test_does_not_apply_to_wire_transfer(self):
        result = _eval(self.adapter, "wire_transfer", {"admin_return_rate_pct": 50.0})
        assert "NACHA_ADMIN_RETURN_RATE_EXCEEDED" not in result.violations


# ===========================================================================
# Nacha — Unauthorized Return Rate Threshold
# ===========================================================================

class TestNachaUnauthorizedReturnRate:
    """unauthorized_return_rate_pct > 0.5% → hard_block."""

    def setup_method(self):
        self.adapter = _adapter("nacha_return_rate_unauthorized.yaml")

    def test_blocks_above_0_5pct(self):
        result = _eval(self.adapter, "ach_payment", {"unauthorized_return_rate_pct": 0.6})
        assert "NACHA_UNAUTHORIZED_RETURN_RATE_EXCEEDED" in result.violations
        assert result.approved is False

    def test_passes_at_exactly_0_5pct(self):
        result = _eval(self.adapter, "ach_payment", {"unauthorized_return_rate_pct": 0.5})
        assert "NACHA_UNAUTHORIZED_RETURN_RATE_EXCEEDED" not in result.violations

    def test_passes_below_0_5pct(self):
        result = _eval(self.adapter, "ach_payment", {"unauthorized_return_rate_pct": 0.4})
        assert result.approved is True

    @pytest.mark.parametrize("rate", [0.51, 1.0, 3.0, 10.0])
    def test_all_over_threshold_blocked(self, rate: float):
        result = _eval(self.adapter, "ach_payment", {"unauthorized_return_rate_pct": rate})
        assert "NACHA_UNAUTHORIZED_RETURN_RATE_EXCEEDED" in result.violations

    def test_does_not_apply_to_wire_transfer(self):
        result = _eval(self.adapter, "wire_transfer", {"unauthorized_return_rate_pct": 5.0})
        assert "NACHA_UNAUTHORIZED_RETURN_RATE_EXCEEDED" not in result.violations

    def test_stricter_than_admin_threshold(self):
        """Unauthorized threshold (0.5%) is stricter than admin (3.0%)."""
        admin = _adapter("nacha_return_rate_admin.yaml")
        unauth = _adapter("nacha_return_rate_unauthorized.yaml")
        # 1.0% triggers unauthorized but NOT admin
        r_admin = _eval(admin, "ach_payment", {"admin_return_rate_pct": 1.0})
        r_unauth = _eval(unauth, "ach_payment", {"unauthorized_return_rate_pct": 1.0})
        assert "NACHA_ADMIN_RETURN_RATE_EXCEEDED" not in r_admin.violations
        assert "NACHA_UNAUTHORIZED_RETURN_RATE_EXCEEDED" in r_unauth.violations


# ===========================================================================
# Nacha — WEB Debit Authorization
# ===========================================================================

class TestNachaWEBDebitAuthorization:
    """Missing web_authorization_ref or account_validation_ref → hard_block."""

    def setup_method(self):
        self.adapter = _adapter("nacha_web_debit_authorization.yaml")

    _FULL = {
        "customer_id":            "CUST-001",
        "account_id":             "ACC-001",
        "web_authorization_ref":  "WEB-AUTH-2026-001",
        "account_validation_ref": "PLAID-VALID-001",
    }

    def test_passes_with_all_required_fields(self):
        result = _eval(self.adapter, "ach_payment", self._FULL)
        assert "NACHA_WEB_DEBIT_AUTHORIZATION_MISSING" not in result.violations

    @pytest.mark.parametrize("missing", [
        "web_authorization_ref",
        "account_validation_ref",
        "customer_id",
        "account_id",
    ])
    def test_blocks_when_field_missing(self, missing: str):
        params = {k: v for k, v in self._FULL.items() if k != missing}
        result = _eval(self.adapter, "ach_payment", params)
        assert "NACHA_WEB_DEBIT_AUTHORIZATION_MISSING" in result.violations

    def test_does_not_apply_to_wire_transfer(self):
        result = _eval(self.adapter, "wire_transfer", {"customer_id": "C1", "account_id": "A1"})
        assert "NACHA_WEB_DEBIT_AUTHORIZATION_MISSING" not in result.violations

    def test_empty_auth_ref_triggers_block(self):
        params = {**self._FULL, "web_authorization_ref": ""}
        result = _eval(self.adapter, "ach_payment", params)
        assert "NACHA_WEB_DEBIT_AUTHORIZATION_MISSING" in result.violations


# ===========================================================================
# Nacha — Micro-Entry Verification
# ===========================================================================

class TestNachaMicroEntryVerification:
    """Missing micro-entry registration / verification refs → hard_block."""

    def setup_method(self):
        self.adapter = _adapter("nacha_micro_entry_verification.yaml")

    _FULL = {
        "customer_id":                   "CUST-001",
        "account_id":                    "ACC-001",
        "micro_entry_registration_ref":  "NACHA-ME-REG-001",
        "micro_entry_verification_ref":  "ME-VERIFY-2026-001",
    }

    def test_passes_with_all_required_fields(self):
        result = _eval(self.adapter, "ach_payment", self._FULL)
        assert "NACHA_MICRO_ENTRY_MISSING" not in result.violations

    @pytest.mark.parametrize("missing", [
        "micro_entry_registration_ref",
        "micro_entry_verification_ref",
        "customer_id",
        "account_id",
    ])
    def test_blocks_when_field_missing(self, missing: str):
        params = {k: v for k, v in self._FULL.items() if k != missing}
        result = _eval(self.adapter, "ach_payment", params)
        assert "NACHA_MICRO_ENTRY_MISSING" in result.violations

    def test_does_not_apply_to_wire(self):
        result = _eval(self.adapter, "wire_transfer", {"customer_id": "C1"})
        assert "NACHA_MICRO_ENTRY_MISSING" not in result.violations


# ===========================================================================
# Nacha — TPSP Authorization
# ===========================================================================

class TestNachaTPSPAuthorization:
    """Missing TPSP registration / ODFI authorization refs → hard_block."""

    def setup_method(self):
        self.adapter = _adapter("nacha_tpsp_authorization.yaml")

    _FULL = {
        "customer_id":              "CUST-001",
        "account_id":               "ACC-001",
        "tpsp_registration_ref":    "TPSP-REG-2026-001",
        "originator_agreement_ref": "ORIG-AGR-2026-001",
        "odfi_authorization_ref":   "ODFI-AUTH-2026-001",
    }

    def test_passes_with_all_required_fields(self):
        result = _eval(self.adapter, "ach_payment", self._FULL)
        assert "NACHA_TPSP_AUTHORIZATION_MISSING" not in result.violations

    @pytest.mark.parametrize("missing", [
        "tpsp_registration_ref",
        "originator_agreement_ref",
        "odfi_authorization_ref",
        "customer_id",
        "account_id",
    ])
    def test_blocks_when_field_missing(self, missing: str):
        params = {k: v for k, v in self._FULL.items() if k != missing}
        result = _eval(self.adapter, "ach_payment", params)
        assert "NACHA_TPSP_AUTHORIZATION_MISSING" in result.violations

    def test_does_not_apply_to_wire(self):
        result = _eval(self.adapter, "wire_transfer", {"customer_id": "C1"})
        assert "NACHA_TPSP_AUTHORIZATION_MISSING" not in result.violations


# ===========================================================================
# Cross-rule integration — FinCEN + Nacha together
# ===========================================================================

class TestFinCENNachaCombined:
    """Multiple FinCEN and Nacha rules loaded together — verify correct isolation."""

    def setup_method(self):
        self.adapter = _adapter(
            "fincen_ctr_threshold.yaml",
            "fincen_structuring.yaml",
            "fincen_sar_trigger.yaml",
            "fincen_beneficial_ownership.yaml",
            "fincen_high_risk_jurisdiction.yaml",
            "nacha_same_day_ach_limit.yaml",
            "nacha_return_rate_admin.yaml",
            "nacha_return_rate_unauthorized.yaml",
            "nacha_web_debit_authorization.yaml",
            "nacha_micro_entry_verification.yaml",
            "nacha_tpsp_authorization.yaml",
        )

    def test_ctr_and_nacha_limit_both_fire_on_large_ach(self):
        """A $2M ACH triggers both CTR (>$10k) and Nacha same-day limit (>$1M)."""
        result = _eval(self.adapter, "ach_payment", {"amount": 2_000_000})
        assert "FINCEN_CTR_REQUIRED" in result.violations
        assert "NACHA_SAME_DAY_LIMIT_EXCEEDED" in result.violations

    def test_structuring_fires_independent_of_amount(self):
        result = _eval(self.adapter, "wire_transfer", {
            "amount": 5000,
            "memo": "structuring the payment below CTR",
        })
        assert "FINCEN_STRUCTURING_DETECTED" in result.violations
        assert "FINCEN_CTR_REQUIRED" not in result.violations  # amount below 10k

    def test_jurisdiction_block_fires_on_wire(self):
        result = _eval(self.adapter, "wire_transfer", {"jurisdiction_code": "KP", "amount": 100})
        assert "FINCEN_HIGH_RISK_JURISDICTION" in result.violations

    def test_clean_ach_passes_all_rules(self):
        result = _eval(self.adapter, "ach_payment", {
            "customer_id": "CUST-001",
            "account_id": "ACC-001",
            "amount": 500,
            "memo": "payroll",
            "jurisdiction_code": "US",
            "web_authorization_ref": "WEB-001",
            "account_validation_ref": "VAL-001",
            "micro_entry_registration_ref": "ME-REG-001",
            "micro_entry_verification_ref": "ME-VER-001",
            "tpsp_registration_ref": "TPSP-001",
            "originator_agreement_ref": "ORIG-001",
            "odfi_authorization_ref": "ODFI-001",
            "admin_return_rate_pct": 0.5,
            "unauthorized_return_rate_pct": 0.1,
            "beneficial_owner_id": "BO-001",
            "beneficial_owner_dob": "1980-01-01",
            "control_prong_name": "John Doe",
        })
        fincen_nacha = [v for v in result.violations if v.startswith(("FINCEN_", "NACHA_"))]
        assert fincen_nacha == []

    def test_sar_and_ctr_both_fire_on_large_suspicious_wire(self):
        result = _eval(self.adapter, "wire_transfer", {
            "amount": 50000,
            "memo": "money laundering proceeds transfer",
        })
        assert "FINCEN_CTR_REQUIRED" in result.violations
        assert "FINCEN_SAR_TRIGGER" in result.violations


# ===========================================================================
# Endpoint integration — /validate with FinCEN / Nacha rules active
# ===========================================================================

@pytest.mark.asyncio
async def test_endpoint_ctr_threshold_fires(async_client: AsyncClient):
    # The shared test app uses a stub data provider that overrides all threshold
    # max_values to $1M. Test at $1.5M so CTR ($10k) AND the data-provider
    # threshold ($1M) are both exceeded, triggering FINCEN_CTR_REQUIRED.
    resp = await async_client.post("/validate", json={
        "action_type": "wire_transfer",
        "parameters": {
            "customer_id": "CUST-001",
            "account_id": "ACC-001",
            "recipient_id": "LEGIT-BANK",
            "amount": 1_500_000,
            "compliance_certification_year": "2026",
            "private_transaction_notice_ref": "PVT-001",
            "finra_filing_ref": "FINRA-PP-001",
            "trace_reporting_ref": "TRACE-001",
            "beneficial_owner_id": "BO-001",
            "beneficial_owner_dob": "1970-01-01",
            "control_prong_name": "Jane Smith",
        },
        "context": {},
        "agent_id": "registered-agent-001",
    })
    assert resp.status_code == 200
    data = resp.json()
    codes = [v["violation_code"] for v in data["violations"]]
    assert "FINCEN_CTR_REQUIRED" in codes


@pytest.mark.asyncio
async def test_endpoint_structuring_hard_blocks(async_client: AsyncClient):
    resp = await async_client.post("/validate", json={
        "action_type": "wire_transfer",
        "parameters": {
            "customer_id": "CUST-001",
            "account_id": "ACC-001",
            "recipient_id": "LEGIT-BANK",
            "amount": 9500,
            "memo": "structuring split payment",
            "compliance_certification_year": "2026",
            "private_transaction_notice_ref": "PVT-001",
            "finra_filing_ref": "FINRA-PP-001",
            "trace_reporting_ref": "TRACE-001",
        },
        "context": {},
        "agent_id": "registered-agent-001",
    })
    assert resp.status_code == 200
    data = resp.json()
    codes = [v["violation_code"] for v in data["violations"]]
    assert "FINCEN_STRUCTURING_DETECTED" in codes
    assert data["approved"] is False


@pytest.mark.asyncio
async def test_endpoint_nacha_limit_hard_blocks(async_client: AsyncClient):
    resp = await async_client.post("/validate", json={
        "action_type": "ach_payment",
        "parameters": {
            "customer_id": "CUST-001",
            "account_id": "ACC-001",
            "amount": 1_500_000,
        },
        "context": {},
        "agent_id": "registered-agent-001",
    })
    assert resp.status_code == 200
    data = resp.json()
    codes = [v["violation_code"] for v in data["violations"]]
    assert "NACHA_SAME_DAY_LIMIT_EXCEEDED" in codes


@pytest.mark.asyncio
async def test_endpoint_high_risk_jurisdiction_hard_blocks(async_client: AsyncClient):
    # The shared test app uses a stub data provider whose is_sanctioned() only
    # returns True for SDN-001/002/003 etc. The fincen_high_risk_jurisdiction rule
    # uses field=jurisdiction_code and the stub provider checks that value via
    # is_sanctioned(). Use "SDN-001" so the stub returns True, simulating a
    # sanctioned-jurisdiction lookup that resolves positive.
    resp = await async_client.post("/validate", json={
        "action_type": "wire_transfer",
        "parameters": {
            "customer_id": "CUST-001",
            "account_id": "ACC-001",
            "recipient_id": "LEGIT-BANK",
            "amount": 100,
            "jurisdiction_code": "SDN-001",
            "compliance_certification_year": "2026",
            "private_transaction_notice_ref": "PVT-001",
            "finra_filing_ref": "FINRA-PP-001",
            "trace_reporting_ref": "TRACE-001",
            "beneficial_owner_id": "BO-001",
            "beneficial_owner_dob": "1970-01-01",
            "control_prong_name": "Jane Smith",
        },
        "context": {},
        "agent_id": "registered-agent-001",
    })
    assert resp.status_code == 200
    data = resp.json()
    codes = [v["violation_code"] for v in data["violations"]]
    assert "FINCEN_HIGH_RISK_JURISDICTION" in codes
    assert data["approved"] is False
