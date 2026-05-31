"""Comprehensive tests for all FINRA rule YAML files loaded via AGTAdapter.

Each rule gets at minimum:
  - a "should block / flag" case (violating input)
  - a "should pass" case (clean input)
  - where relevant, a boundary / edge case

Pattern-match rules are tested by constructing inputs whose field value
matches or doesn't match the regex documented in the YAML params.
Required-fields rules are tested by omitting vs. supplying the mandatory keys.
Threshold rules are tested at just-above, just-at, and just-below the limit.
Account-status rules are tested with a populated frozen_accounts list.
Sanctions rules are tested with a populated sanctions_list.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.engine.models import PolicyRule, Severity
from src.engine.rule_loader import load_policy_rules
from src.engine.agt_adapter import AGTAdapter
from src.rules.models import CheckType


RULES_DIR = Path(__file__).parent.parent / "rules"


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------


def _make_adapter(*rule_files: str) -> AGTAdapter:
    """Return an AGTAdapter pre-loaded with specific rule YAML files from rules/."""
    import tempfile, shutil, os

    tmp = Path(tempfile.mkdtemp())
    for name in rule_files:
        src = RULES_DIR / name
        if src.exists():
            shutil.copy(src, tmp / name)
    return AGTAdapter(rules_dir=tmp)


def _adapter_with_override(rule_file: str, **param_overrides) -> AGTAdapter:
    """Return an AGTAdapter for one rule with its params overridden (e.g. to populate empty lists)."""
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    data = yaml.safe_load((RULES_DIR / rule_file).read_text())
    data["params"].update(param_overrides)
    (tmp / rule_file).write_text(yaml.dump(data))
    return AGTAdapter(rules_dir=tmp)


# ===========================================================================
# 1. THRESHOLD RULES
# ===========================================================================


class TestRule2121FairCommissions:
    """FINRA Rule 2121 — Fair Prices and Commissions (5 % cap on equity trades)."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_2121.yaml")

    def test_flags_commission_above_5pct(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "amount": 10000, "commission_rate_pct": 6.0},
            {},
            "agent-1",
        )
        assert "EXCESSIVE_COMMISSION" in result.violations

    def test_passes_commission_at_5pct(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "amount": 10000, "commission_rate_pct": 5.0},
            {},
            "agent-1",
        )
        assert "EXCESSIVE_COMMISSION" not in result.violations

    def test_passes_commission_below_5pct(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "amount": 10000, "commission_rate_pct": 1.5},
            {},
            "agent-1",
        )
        assert result.approved is True

    def test_does_not_apply_to_wire_transfer(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"amount": 5000, "commission_rate_pct": 99.0},
            {},
            "agent-1",
        )
        assert "EXCESSIVE_COMMISSION" not in result.violations


class TestRule2341MutualFundNAV:
    """FINRA Rule 2341 — Mutual Fund price must be within 1 % of NAV."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_2341.yaml")

    def test_flags_nav_deviation_above_1pct(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "nav_deviation_pct": 2.5},
            {},
            "agent-1",
        )
        assert "MUTUAL_FUND_PRICE_DEVIATION" in result.violations

    def test_passes_nav_deviation_at_1pct(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "nav_deviation_pct": 1.0},
            {},
            "agent-1",
        )
        assert "MUTUAL_FUND_PRICE_DEVIATION" not in result.violations

    def test_passes_zero_deviation(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "nav_deviation_pct": 0.0},
            {},
            "agent-1",
        )
        assert result.approved is True


class TestRule2370FuturesMargin:
    """FINRA Rule 2370 — Futures initial margin must be at least 20 %."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_2370.yaml")

    def test_blocks_margin_above_threshold(self):
        # futures_margin_pct > 20 means insufficient margin posted (field is the deficit %)
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "futures_margin_pct": 25.0},
            {},
            "agent-1",
        )
        assert "FUTURES_MARGIN_INSUFFICIENT" in result.violations

    def test_passes_margin_at_threshold(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "futures_margin_pct": 20.0},
            {},
            "agent-1",
        )
        assert "FUTURES_MARGIN_INSUFFICIENT" not in result.violations

    def test_passes_margin_below_threshold(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "futures_margin_pct": 10.0},
            {},
            "agent-1",
        )
        assert result.approved is True


class TestRule3110SupervisionWireThreshold:
    """FINRA Rule 3110 — Wire transfers > $1 000 000 need human supervisory approval."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_3110.yaml")

    def test_soft_holds_wire_above_1m(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"recipient_id": "BANK-A", "amount": 1_500_000},
            {},
            "agent-1",
        )
        assert "SUPERVISION_WIRE_THRESHOLD_EXCEEDED" in result.violations

    def test_passes_wire_at_1m(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"recipient_id": "BANK-A", "amount": 1_000_000},
            {},
            "agent-1",
        )
        assert "SUPERVISION_WIRE_THRESHOLD_EXCEEDED" not in result.violations

    def test_passes_wire_below_1m(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"recipient_id": "BANK-A", "amount": 999_999},
            {},
            "agent-1",
        )
        assert result.approved is True

    def test_does_not_apply_to_equity_trade(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"amount": 5_000_000},
            {},
            "agent-1",
        )
        assert "SUPERVISION_WIRE_THRESHOLD_EXCEEDED" not in result.violations


class TestRule4110CapitalCompliance:
    """FINRA Rule 4110 — ACH / wire transfers > $25 000 000 trigger capital review."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_4110.yaml")

    def test_soft_holds_above_25m(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"amount": 26_000_000},
            {},
            "agent-1",
        )
        assert "CAPITAL_COMPLIANCE_RISK" in result.violations

    def test_passes_at_25m(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"amount": 25_000_000},
            {},
            "agent-1",
        )
        assert "CAPITAL_COMPLIANCE_RISK" not in result.violations

    def test_ach_payment_also_checked(self):
        result = self.adapter.evaluate(
            "ach_payment",
            {"amount": 30_000_000},
            {},
            "agent-1",
        )
        assert "CAPITAL_COMPLIANCE_RISK" in result.violations


class TestRule4210MarginRequirements:
    """FINRA Rule 4210 — Reg T initial margin must be ≥ 50 %."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_4210.yaml")

    def test_blocks_margin_above_50pct(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "margin_rate_pct": 55.0},
            {},
            "agent-1",
        )
        assert "MARGIN_REQUIREMENT_INSUFFICIENT" in result.violations

    def test_passes_margin_at_50pct(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "margin_rate_pct": 50.0},
            {},
            "agent-1",
        )
        assert "MARGIN_REQUIREMENT_INSUFFICIENT" not in result.violations


class TestRule5110UnderwritingCompensation:
    """FINRA Rule 5110 — Underwriting compensation must not exceed 10 %."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_5110.yaml")

    def test_flags_compensation_above_10pct(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "underwriting_compensation_pct": 12.0},
            {},
            "agent-1",
        )
        assert "UNDERWRITING_COMPENSATION_EXCESSIVE" in result.violations

    def test_passes_compensation_at_10pct(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "underwriting_compensation_pct": 10.0},
            {},
            "agent-1",
        )
        assert "UNDERWRITING_COMPENSATION_EXCESSIVE" not in result.violations


# ===========================================================================
# 2. REQUIRED-FIELDS RULES
# ===========================================================================


class TestRule2090KYC:
    """FINRA Rule 2090 — Know Your Customer (customer_id + account_id required)."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_kyc_2090.yaml")

    def test_blocks_missing_customer_id(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"account_id": "ACC-1", "amount": 5000},
            {},
            "agent-1",
        )
        assert "KYC_MISSING_FIELDS" in result.violations

    def test_blocks_missing_account_id(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"customer_id": "CUST-1", "amount": 5000},
            {},
            "agent-1",
        )
        assert "KYC_MISSING_FIELDS" in result.violations

    def test_blocks_both_fields_missing(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"amount": 5000},
            {},
            "agent-1",
        )
        assert "KYC_MISSING_FIELDS" in result.violations

    def test_passes_with_all_required_fields(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"customer_id": "CUST-1", "account_id": "ACC-1", "amount": 5000},
            {},
            "agent-1",
        )
        assert "KYC_MISSING_FIELDS" not in result.violations

    def test_blocks_empty_string_fields(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"customer_id": "", "account_id": "ACC-1"},
            {},
            "agent-1",
        )
        assert "KYC_MISSING_FIELDS" in result.violations


class TestRule2214AnalysisToolDisclosure:
    """FINRA Rule 2214 — Analysis tool disclosure reference required."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_2214.yaml")

    def test_flags_missing_disclosure_ref(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1"},
            {},
            "agent-1",
        )
        assert "ANALYSIS_TOOL_DISCLOSURE_MISSING" in result.violations

    def test_passes_with_disclosure_ref(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "analysis_tool_disclosure_ref": "DISC-2024-001"},
            {},
            "agent-1",
        )
        assert "ANALYSIS_TOOL_DISCLOSURE_MISSING" not in result.violations


class TestRule2268ArbitrationDisclosure:
    """FINRA Rule 2268 — Arbitration agreement reference required on account_open."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_2268.yaml")

    def test_flags_missing_arbitration_ref(self):
        result = self.adapter.evaluate(
            "account_open",
            {"customer_id": "C1", "account_id": "A1"},
            {},
            "agent-1",
        )
        assert "ARBITRATION_DISCLOSURE_MISSING" in result.violations

    def test_passes_with_arbitration_ref(self):
        result = self.adapter.evaluate(
            "account_open",
            {"customer_id": "C1", "account_id": "A1", "arbitration_agreement_ref": "ARB-2024-001"},
            {},
            "agent-1",
        )
        assert "ARBITRATION_DISCLOSURE_MISSING" not in result.violations

    def test_does_not_apply_to_wire_transfer(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"customer_id": "C1", "account_id": "A1"},
            {},
            "agent-1",
        )
        assert "ARBITRATION_DISCLOSURE_MISSING" not in result.violations


class TestRule2310DPPSuitability:
    """FINRA Rule 2310 — DPP suitability assessment required for equity trades."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_2310.yaml")

    def test_flags_missing_suitability_ref(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1"},
            {},
            "agent-1",
        )
        assert "DPP_SUITABILITY_MISSING" in result.violations

    def test_passes_with_suitability_ref(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "suitability_assessment_ref": "SUIT-001"},
            {},
            "agent-1",
        )
        assert "DPP_SUITABILITY_MISSING" not in result.violations


class TestRule2320VariableContractSuitability:
    """FINRA Rule 2320 — investment_objective + suitability_assessment_ref required."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_2320.yaml")

    def test_flags_missing_investment_objective(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "suitability_assessment_ref": "SUIT-001"},
            {},
            "agent-1",
        )
        assert "VARIABLE_CONTRACT_SUITABILITY_MISSING" in result.violations

    def test_flags_missing_suitability_ref(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "investment_objective": "growth"},
            {},
            "agent-1",
        )
        assert "VARIABLE_CONTRACT_SUITABILITY_MISSING" in result.violations

    def test_passes_with_all_required_fields(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "investment_objective": "growth", "suitability_assessment_ref": "SUIT-001"},
            {},
            "agent-1",
        )
        assert "VARIABLE_CONTRACT_SUITABILITY_MISSING" not in result.violations


class TestRule2360OptionsApproval:
    """FINRA Rule 2360 — options_approval_level required for options trades."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_2360.yaml")

    def test_flags_missing_options_approval(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1"},
            {},
            "agent-1",
        )
        assert "OPTIONS_ACCOUNT_NOT_APPROVED" in result.violations

    def test_passes_with_options_approval(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "options_approval_level": "2"},
            {},
            "agent-1",
        )
        assert "OPTIONS_ACCOUNT_NOT_APPROVED" not in result.violations


class TestRule3130ComplianceCertification:
    """FINRA Rule 3130 — compliance_certification_year required."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_3130.yaml")

    def test_flags_missing_certification_year(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"customer_id": "C1", "account_id": "A1"},
            {},
            "agent-1",
        )
        assert "COMPLIANCE_CERTIFICATION_MISSING" in result.violations

    def test_passes_with_certification_year(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"customer_id": "C1", "account_id": "A1", "compliance_certification_year": "2026"},
            {},
            "agent-1",
        )
        assert "COMPLIANCE_CERTIFICATION_MISSING" not in result.violations


class TestRule3260DiscretionaryAuthorization:
    """FINRA Rule 3260 — discretionary_authorization_ref required."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_3260.yaml")

    def test_flags_missing_authorization(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1"},
            {},
            "agent-1",
        )
        assert "DISCRETIONARY_AUTHORIZATION_MISSING" in result.violations

    def test_passes_with_authorization(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "discretionary_authorization_ref": "AUTH-2024-007"},
            {},
            "agent-1",
        )
        assert "DISCRETIONARY_AUTHORIZATION_MISSING" not in result.violations


class TestRule3280PrivateSecuritiesNotice:
    """FINRA Rule 3280 — private_transaction_notice_ref required."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_3280.yaml")

    def test_flags_missing_notice_ref(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1"},
            {},
            "agent-1",
        )
        assert "PRIVATE_SECURITIES_NOTICE_MISSING" in result.violations

    def test_passes_with_notice_ref(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "private_transaction_notice_ref": "PVT-2024-003"},
            {},
            "agent-1",
        )
        assert "PRIVATE_SECURITIES_NOTICE_MISSING" not in result.violations


class TestRule4512CustomerAccountInfo:
    """FINRA Rule 4512 — date_of_birth + investment_objective required on account open."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_4512.yaml")

    def test_flags_missing_dob(self):
        result = self.adapter.evaluate(
            "account_open",
            {"customer_id": "C1", "account_id": "A1", "investment_objective": "income"},
            {},
            "agent-1",
        )
        assert "CUSTOMER_ACCOUNT_INFO_MISSING" in result.violations

    def test_flags_missing_investment_objective(self):
        result = self.adapter.evaluate(
            "account_open",
            {"customer_id": "C1", "account_id": "A1", "date_of_birth": "1980-01-01"},
            {},
            "agent-1",
        )
        assert "CUSTOMER_ACCOUNT_INFO_MISSING" in result.violations

    def test_passes_with_all_required_fields(self):
        result = self.adapter.evaluate(
            "account_open",
            {"customer_id": "C1", "account_id": "A1", "date_of_birth": "1980-01-01", "investment_objective": "growth"},
            {},
            "agent-1",
        )
        assert "CUSTOMER_ACCOUNT_INFO_MISSING" not in result.violations


class TestRule4517AccountRecord:
    """FINRA Rule 4517 — tax_id_ref + date_of_birth required."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_4517.yaml")

    def test_flags_missing_tax_id(self):
        result = self.adapter.evaluate(
            "account_open",
            {"customer_id": "C1", "account_id": "A1", "date_of_birth": "1975-06-15"},
            {},
            "agent-1",
        )
        assert "ACCOUNT_RECORD_INCOMPLETE" in result.violations

    def test_passes_with_all_fields(self):
        result = self.adapter.evaluate(
            "account_open",
            {"customer_id": "C1", "account_id": "A1", "date_of_birth": "1975-06-15", "tax_id_ref": "TAX-XXXX-1234"},
            {},
            "agent-1",
        )
        assert "ACCOUNT_RECORD_INCOMPLETE" not in result.violations


class TestRule5121OfferingConflictDisclosure:
    """FINRA Rule 5121 — conflict_disclosure_ref required."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_5121.yaml")

    def test_flags_missing_conflict_disclosure(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1"},
            {},
            "agent-1",
        )
        assert "OFFERING_CONFLICT_DISCLOSURE_MISSING" in result.violations

    def test_passes_with_conflict_disclosure(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "conflict_disclosure_ref": "CONF-2024-009"},
            {},
            "agent-1",
        )
        assert "OFFERING_CONFLICT_DISCLOSURE_MISSING" not in result.violations


class TestRule5122PrivatePlacementFiling:
    """FINRA Rule 5122 — finra_filing_ref required."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_5122.yaml")

    def test_flags_missing_filing_ref(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1"},
            {},
            "agent-1",
        )
        assert "MEMBER_PRIVATE_PLACEMENT_FILING_MISSING" in result.violations

    def test_passes_with_filing_ref(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "finra_filing_ref": "FINRA-PP-2024-0042"},
            {},
            "agent-1",
        )
        assert "MEMBER_PRIVATE_PLACEMENT_FILING_MISSING" not in result.violations


class TestRule6710TraceReporting:
    """FINRA Rule 6710 — trace_reporting_ref required for wire + ach."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_6710.yaml")

    def test_flags_missing_trace_ref_wire(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"customer_id": "C1", "account_id": "A1"},
            {},
            "agent-1",
        )
        assert "TRACE_REPORTING_MISSING" in result.violations

    def test_flags_missing_trace_ref_ach(self):
        result = self.adapter.evaluate(
            "ach_payment",
            {"customer_id": "C1", "account_id": "A1"},
            {},
            "agent-1",
        )
        assert "TRACE_REPORTING_MISSING" in result.violations

    def test_passes_with_trace_ref(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"customer_id": "C1", "account_id": "A1", "trace_reporting_ref": "TRACE-20260530-001"},
            {},
            "agent-1",
        )
        assert "TRACE_REPORTING_MISSING" not in result.violations


# ===========================================================================
# 3. ACCOUNT-STATUS RULES
# ===========================================================================


class TestRuleAccountFreeze:
    """FINRA Account Freeze — blocks all actions on frozen accounts."""

    def setup_method(self):
        self.adapter = _adapter_with_override(
            "finra_account_freeze.yaml",
            frozen_accounts=["FROZEN-001", "FROZEN-002"],
        )

    def test_blocks_wire_on_frozen_account(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"account_id": "FROZEN-001", "amount": 1000},
            {},
            "agent-1",
        )
        assert "ACCOUNT_FROZEN" in result.violations
        assert result.approved is False

    def test_blocks_equity_trade_on_frozen_account(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"account_id": "FROZEN-002"},
            {},
            "agent-1",
        )
        assert "ACCOUNT_FROZEN" in result.violations

    def test_passes_clean_account(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"account_id": "CLEAN-ACC", "amount": 1000},
            {},
            "agent-1",
        )
        assert "ACCOUNT_FROZEN" not in result.violations


class TestRule2165SpecifiedAdultExploitation:
    """FINRA Rule 2165 — Holds transfers from exploitation-flagged accounts."""

    def setup_method(self):
        self.adapter = _adapter_with_override(
            "finra_rule_2165.yaml",
            frozen_accounts=["SA-ACCT-001"],
        )

    def test_soft_holds_wire_on_flagged_account(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"account_id": "SA-ACCT-001", "amount": 5000},
            {},
            "agent-1",
        )
        assert "SPECIFIED_ADULT_EXPLOITATION_HOLD" in result.violations

    def test_soft_holds_ach_on_flagged_account(self):
        result = self.adapter.evaluate(
            "ach_payment",
            {"account_id": "SA-ACCT-001", "amount": 500},
            {},
            "agent-1",
        )
        assert "SPECIFIED_ADULT_EXPLOITATION_HOLD" in result.violations

    def test_passes_unflagged_account(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"account_id": "NORMAL-ACC", "amount": 5000},
            {},
            "agent-1",
        )
        assert "SPECIFIED_ADULT_EXPLOITATION_HOLD" not in result.violations


class TestRule4511BooksRecords:
    """FINRA Rule 4511 — Books and records frozen account blocks all actions."""

    def setup_method(self):
        self.adapter = _adapter_with_override(
            "finra_rule_4511.yaml",
            frozen_accounts=["RECORDS-FROZEN-001"],
        )

    def test_blocks_any_action_on_records_frozen_account(self):
        for action in ("wire_transfer", "equity_trade", "ach_payment", "account_open"):
            result = self.adapter.evaluate(
                action,
                {"account_id": "RECORDS-FROZEN-001"},
                {},
                "agent-1",
            )
            assert "BOOKS_RECORDS_ACCOUNT_FROZEN" in result.violations, f"Expected block for {action}"


class TestRule5130IPORestrictedPerson:
    """FINRA Rule 5130 — IPO restricted persons cannot receive new issues."""

    def setup_method(self):
        self.adapter = _adapter_with_override(
            "finra_rule_5130.yaml",
            frozen_accounts=["RESTRICTED-PERSON-001"],
        )

    def test_blocks_ipo_for_restricted_account(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"account_id": "RESTRICTED-PERSON-001", "ticker": "NEWCO"},
            {},
            "agent-1",
        )
        assert "IPO_RESTRICTED_PERSON" in result.violations

    def test_passes_non_restricted_account(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"account_id": "PUBLIC-ACC", "ticker": "NEWCO"},
            {},
            "agent-1",
        )
        assert "IPO_RESTRICTED_PERSON" not in result.violations


class TestRule8310DisciplinarySanction:
    """FINRA Rule 8310 — Active disciplinary sanction blocks all actions (keyed on agent_id field)."""

    def setup_method(self):
        self.adapter = _adapter_with_override(
            "finra_rule_8310.yaml",
            frozen_accounts=["SANCTIONED-AGENT-001"],
        )

    def test_blocks_all_actions_for_sanctioned_agent(self):
        # Rule uses field: agent_id — pass it in parameters so the engine can read it
        for action in ("wire_transfer", "equity_trade", "loan_decision"):
            result = self.adapter.evaluate(
                action,
                {"agent_id": "SANCTIONED-AGENT-001", "account_id": "ACC-1"},
                {},
                "audit-agent",
            )
            assert "DISCIPLINARY_SANCTION_ACTIVE" in result.violations, f"Expected block for {action}"

    def test_passes_non_sanctioned_agent(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"agent_id": "CLEAN-AGENT-001", "account_id": "ACC-1"},
            {},
            "audit-agent",
        )
        assert "DISCIPLINARY_SANCTION_ACTIVE" not in result.violations


class TestRule9551CeaseAndDesist:
    """FINRA Rule 9551 — Cease-and-desist order blocks all actions."""

    def setup_method(self):
        self.adapter = _adapter_with_override(
            "finra_rule_9551.yaml",
            frozen_accounts=["CD-ENTITY-001"],
        )

    def test_blocks_wire_on_cd_entity(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"account_id": "CD-ENTITY-001", "amount": 1000},
            {},
            "agent-1",
        )
        assert "CEASE_AND_DESIST_ORDER" in result.violations
        assert result.approved is False

    def test_passes_non_cd_entity(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"account_id": "NORMAL-ENTITY", "amount": 1000},
            {},
            "agent-1",
        )
        assert "CEASE_AND_DESIST_ORDER" not in result.violations


# ===========================================================================
# 4. SANCTIONS / AML RULES
# ===========================================================================


class TestRule3310AMLSanctions:
    """FINRA Rule 3310 — AML: wire transfers to OFAC-listed recipients blocked."""

    def setup_method(self):
        self.adapter = _adapter_with_override(
            "finra_rule_3310.yaml",
            sanctions_list=["SDN-AML-001", "BLOCKED-SHELL-CO"],
        )

    def test_blocks_transfer_to_sanctioned_recipient(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"recipient_id": "SDN-AML-001", "amount": 5000},
            {},
            "agent-1",
        )
        assert "AML_SANCTIONS_MATCH" in result.violations
        assert result.approved is False

    def test_blocks_ach_to_sanctioned_recipient(self):
        result = self.adapter.evaluate(
            "ach_payment",
            {"recipient_id": "BLOCKED-SHELL-CO", "amount": 500},
            {},
            "agent-1",
        )
        assert "AML_SANCTIONS_MATCH" in result.violations

    def test_passes_clean_recipient(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"recipient_id": "LEGIT-BANK-USA", "amount": 5000},
            {},
            "agent-1",
        )
        assert "AML_SANCTIONS_MATCH" not in result.violations


# ===========================================================================
# 5. PATTERN-MATCH RULES
# ===========================================================================


class TestRule0140ExemptedSecurity:
    """FINRA Rule 0140 — Exempted security types trigger review."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_0140.yaml")

    @pytest.mark.parametrize("security_type", ["government", "municipal", "muni bond", "Treasury note", "agency MBS"])
    def test_flags_exempted_security_types(self, security_type: str):
        result = self.adapter.evaluate(
            "equity_trade",
            {"security_type": security_type, "customer_id": "C1", "account_id": "A1"},
            {},
            "agent-1",
        )
        assert "EXEMPTED_SECURITY_REVIEW" in result.violations

    def test_passes_standard_equity(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"security_type": "common_stock", "customer_id": "C1", "account_id": "A1"},
            {},
            "agent-1",
        )
        assert "EXEMPTED_SECURITY_REVIEW" not in result.violations


class TestRule1210UnregisteredAgent:
    """FINRA Rule 1210 — Unregistered / inactive agent IDs flagged (field: agent_id)."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_1210.yaml")

    @pytest.mark.parametrize("agent_id", ["unregistered-007", "temp-agent-42", "inactive-rep-5", "UNREG-BOT"])
    def test_flags_unregistered_agent(self, agent_id: str):
        # Pattern match reads parameters["agent_id"]
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "agent_id": agent_id},
            {},
            agent_id,
        )
        assert "REGISTRATION_REQUIRED" in result.violations

    def test_passes_registered_agent(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "agent_id": "registered-agent-001"},
            {},
            "registered-agent-001",
        )
        assert "REGISTRATION_REQUIRED" not in result.violations


class TestRule1220RegistrationCategoryMismatch:
    """FINRA Rule 1220 — IA / RIA agents flagged for broker-dealer actions."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_1220.yaml")

    @pytest.mark.parametrize("agent_id", ["IA-bot-001", "ADVISOR-sys-7", "RIA-agent"])
    def test_flags_ia_agent(self, agent_id: str):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "agent_id": agent_id},
            {},
            agent_id,
        )
        assert "REGISTRATION_CATEGORY_MISMATCH" in result.violations

    def test_passes_bd_agent(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "agent_id": "broker-agent-001"},
            {},
            "broker-agent-001",
        )
        assert "REGISTRATION_CATEGORY_MISMATCH" not in result.violations


class TestRule1230ExemptPersonRestriction:
    """FINRA Rule 1230 — Clerks / admin / ops-exempt agents blocked from trading."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_1230.yaml")

    @pytest.mark.parametrize("agent_id", ["CLERK-001", "ADMIN-assistant", "SUPPORT-bot", "OPS-EXEMPT-sys"])
    def test_flags_exempt_person_agent(self, agent_id: str):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "agent_id": agent_id},
            {},
            agent_id,
        )
        assert "EXEMPT_PERSON_RESTRICTED_ACTIVITY" in result.violations

    def test_passes_normal_agent(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "agent_id": "trader-agent-001"},
            {},
            "trader-agent-001",
        )
        assert "EXEMPT_PERSON_RESTRICTED_ACTIVITY" not in result.violations


class TestRule1240CERequirementLapsed:
    """FINRA Rule 1240 — Agents with lapsed CE blocked."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_1240.yaml")

    @pytest.mark.parametrize("agent_id", ["CE-LAPSED-001", "CE-INACTIVE-rep", "CE-EXPIRED-2024"])
    def test_flags_lapsed_ce_agent(self, agent_id: str):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "agent_id": agent_id},
            {},
            agent_id,
        )
        assert "CE_REQUIREMENT_LAPSED" in result.violations

    def test_passes_agent_with_current_ce(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "agent_id": "active-rep-2026"},
            {},
            "active-rep-2026",
        )
        assert "CE_REQUIREMENT_LAPSED" not in result.violations


class TestRule2010CommercialHonor:
    """FINRA Rule 2010 — Wash trades, manipulation keywords in memo flagged."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_2010.yaml")

    @pytest.mark.parametrize("memo", [
        "fictitious order",
        "sham transaction",
        "wash trade",
        "front run order",
        "market manipulation scheme",
        "pump and dump",
        "layering orders",
        "spoofing activity",
    ])
    def test_flags_manipulative_memo(self, memo: str):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "memo": memo},
            {},
            "agent-1",
        )
        assert "COMMERCIAL_HONOR_VIOLATION" in result.violations

    def test_passes_clean_memo(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "memo": "standard equity purchase"},
            {},
            "agent-1",
        )
        assert "COMMERCIAL_HONOR_VIOLATION" not in result.violations


class TestRule2070FINRAEmployeeTransaction:
    """FINRA Rule 2070 — Transactions by FINRA employees flagged."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_2070.yaml")

    @pytest.mark.parametrize("customer_id", ["FINRA-EMP-001", "FINRA_EMPLOYEE-jones"])
    def test_flags_finra_employee_customer(self, customer_id: str):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": customer_id, "account_id": "A1"},
            {},
            "agent-1",
        )
        assert "FINRA_EMPLOYEE_TRANSACTION" in result.violations

    def test_passes_non_employee_customer(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "RETAIL-CUST-001", "account_id": "A1"},
            {},
            "agent-1",
        )
        assert "FINRA_EMPLOYEE_TRANSACTION" not in result.violations


class TestRule2210MisleadingCommunication:
    """FINRA Rule 2210 — Guaranteed return / risk-free language in memo flagged."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_2210.yaml")

    @pytest.mark.parametrize("memo", [
        "guaranteed return of 20%",
        "risk-free investment",
        "no risk at all",
        "certain profit guaranteed",
        "100% safe strategy",
        "double your money fast",
        "get rich quick scheme",
    ])
    def test_flags_misleading_language(self, memo: str):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "memo": memo},
            {},
            "agent-1",
        )
        assert "MISLEADING_COMMUNICATION" in result.violations

    def test_passes_neutral_memo(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "memo": "diversified equity portfolio rebalance"},
            {},
            "agent-1",
        )
        assert "MISLEADING_COMMUNICATION" not in result.violations


class TestRule2241ResearchAnalystConflict:
    """FINRA Rule 2241 — Research analyst IDs flagged for equity trading."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_2241.yaml")

    @pytest.mark.parametrize("agent_id", ["research-dept", "analyst-001", "RA-equity-team"])
    def test_flags_research_analyst_agent(self, agent_id: str):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "agent_id": agent_id},
            {},
            agent_id,
        )
        assert "RESEARCH_ANALYST_CONFLICT" in result.violations

    def test_passes_non_analyst_agent(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "agent_id": "trading-desk-bot"},
            {},
            "trading-desk-bot",
        )
        assert "RESEARCH_ANALYST_CONFLICT" not in result.violations


class TestRule2242DebtResearchConflict:
    """FINRA Rule 2242 — Debt research analyst IDs flagged."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_2242.yaml")

    @pytest.mark.parametrize("agent_id", ["DEBT-ANALYST-001", "FIXED-INCOME-RA-07", "FI-RESEARCH-bot"])
    def test_flags_debt_research_agent(self, agent_id: str):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"recipient_id": "BANK-A", "agent_id": agent_id},
            {},
            agent_id,
        )
        assert "DEBT_RESEARCH_ANALYST_CONFLICT" in result.violations

    def test_passes_non_debt_research_agent(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"recipient_id": "BANK-A", "agent_id": "operations-bot-01"},
            {},
            "operations-bot-01",
        )
        assert "DEBT_RESEARCH_ANALYST_CONFLICT" not in result.violations


class TestRule3120SupervisoryControl:
    """FINRA Rule 3120 — Unauthorised / test agent IDs flagged."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_3120.yaml")

    @pytest.mark.parametrize("agent_id", ["unregistered-bot", "temp-agent", "test-system", "UNAUTH-process"])
    def test_flags_unauthorised_agent(self, agent_id: str):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"recipient_id": "BANK-A", "amount": 1000, "agent_id": agent_id},
            {},
            agent_id,
        )
        assert "SUPERVISORY_CONTROL_VIOLATION" in result.violations

    def test_passes_authorised_agent(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"recipient_id": "BANK-A", "amount": 1000, "agent_id": "authorised-agent-007"},
            {},
            "authorised-agent-007",
        )
        assert "SUPERVISORY_CONTROL_VIOLATION" not in result.violations


class TestRule3170TapeRecording:
    """FINRA Rule 3170 — Disciplined-firm agents require tape recording."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_3170.yaml")

    @pytest.mark.parametrize("agent_id", ["TAPE-REQUIRED-firm", "DISCIPLINED-FIRM-rep"])
    def test_flags_tape_required_agent(self, agent_id: str):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"recipient_id": "BANK-A", "agent_id": agent_id},
            {},
            agent_id,
        )
        assert "TAPE_RECORDING_REQUIRED" in result.violations

    def test_passes_normal_agent(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"recipient_id": "BANK-A", "agent_id": "standard-agent-001"},
            {},
            "standard-agent-001",
        )
        assert "TAPE_RECORDING_REQUIRED" not in result.violations


class TestRule3210OutsideAccount:
    """FINRA Rule 3210 — Transfers to unapproved outside brokerage accounts blocked."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_3210.yaml")

    @pytest.mark.parametrize("recipient_id", ["EXT-BD-fidelity", "OUTSIDE-ACCT-schwab", "OUTSIDE_BROKER-etrade"])
    def test_flags_outside_broker_recipient(self, recipient_id: str):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"recipient_id": recipient_id, "amount": 5000},
            {},
            "agent-1",
        )
        assert "OUTSIDE_ACCOUNT_NOT_APPROVED" in result.violations

    def test_passes_internal_recipient(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"recipient_id": "INTERNAL-ACCT-001", "amount": 5000},
            {},
            "agent-1",
        )
        assert "OUTSIDE_ACCOUNT_NOT_APPROVED" not in result.violations


class TestRule4120RegulatoryHalt:
    """FINRA Rule 4120 — Trading halted tickers blocked."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_4120.yaml")

    @pytest.mark.parametrize("ticker", ["HALT-TICKER", "SUSPENDED-TICKER-XYZ"])
    def test_blocks_halted_ticker(self, ticker: str):
        result = self.adapter.evaluate(
            "equity_trade",
            {"ticker": ticker, "customer_id": "C1", "account_id": "A1"},
            {},
            "agent-1",
        )
        assert "REGULATORY_HALT_ACTIVE" in result.violations

    def test_passes_active_ticker(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"ticker": "AAPL", "customer_id": "C1", "account_id": "A1"},
            {},
            "agent-1",
        )
        assert "REGULATORY_HALT_ACTIVE" not in result.violations


class TestRule5340AntiIntimidation:
    """FINRA Rule 5340 — Coordination / collusion language in memo flagged."""

    def setup_method(self):
        self.adapter = _make_adapter("finra_rule_5340.yaml")

    @pytest.mark.parametrize("memo", [
        "coordinating with other dealers",
        "colluding to fix price",
        "price fixing arrangement",
        "agreed on price before market open",
        "pre-arranged trade",
        "intimidating the market maker",
    ])
    def test_flags_collusion_memo(self, memo: str):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "memo": memo},
            {},
            "agent-1",
        )
        assert "ANTI_INTIMIDATION_COORDINATION" in result.violations

    def test_passes_clean_memo(self):
        result = self.adapter.evaluate(
            "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "memo": "standard market order"},
            {},
            "agent-1",
        )
        assert "ANTI_INTIMIDATION_COORDINATION" not in result.violations


# ===========================================================================
# 6. ADDITIONAL RULES (adverse action, geo concentration, Reg SHO, suspicious routing)
# ===========================================================================


class TestAdverseActionNotice:
    """ECOA / Reg B — Adverse action notice must be present on loan decisions."""

    def setup_method(self):
        self.adapter = _make_adapter("adverse_action.yaml")

    @pytest.mark.parametrize("flag", ["missing_notice", "incomplete_notice", "no_notice", "notice_defect"])
    def test_flags_defective_notice(self, flag: str):
        result = self.adapter.evaluate(
            "loan_decision",
            {"customer_id": "C1", "account_id": "A1", "adverse_action_flag": flag},
            {},
            "agent-1",
        )
        assert "ADVERSE_ACTION_NOTICE_DEFECT" in result.violations

    def test_passes_compliant_notice(self):
        result = self.adapter.evaluate(
            "loan_decision",
            {"customer_id": "C1", "account_id": "A1", "adverse_action_flag": "notice_sent"},
            {},
            "agent-1",
        )
        assert "ADVERSE_ACTION_NOTICE_DEFECT" not in result.violations


class TestGeoConcentration:
    """CRA / fair lending — Geographic concentration risk flagged."""

    def setup_method(self):
        self.adapter = _make_adapter("geo_concentration.yaml")

    @pytest.mark.parametrize("flag", ["concentrated", "redline_risk", "single_tract", "cra_gap"])
    def test_flags_concentration_risk(self, flag: str):
        result = self.adapter.evaluate(
            "loan_decision",
            {"customer_id": "C1", "account_id": "A1", "geographic_flag": flag},
            {},
            "agent-1",
        )
        assert "GEOGRAPHIC_CONCENTRATION" in result.violations

    def test_passes_diversified_loan(self):
        result = self.adapter.evaluate(
            "loan_decision",
            {"customer_id": "C1", "account_id": "A1", "geographic_flag": "diversified"},
            {},
            "agent-1",
        )
        assert "GEOGRAPHIC_CONCENTRATION" not in result.violations


class TestRegSHOLocate:
    """SEC Reg SHO — Short sells require a confirmed locate."""

    def setup_method(self):
        self.adapter = _make_adapter("reg_sho_locate.yaml")

    @pytest.mark.parametrize("locate", ["false", "no", "0", "missing", "none"])
    def test_blocks_short_sell_without_locate(self, locate: str):
        result = self.adapter.evaluate(
            "short_sell",
            {"locate_confirmed": locate, "ticker": "AAPL"},
            {},
            "agent-1",
        )
        assert "REG_SHO_NO_LOCATE" in result.violations

    def test_passes_confirmed_locate(self):
        result = self.adapter.evaluate(
            "short_sell",
            {"locate_confirmed": "true", "ticker": "AAPL"},
            {},
            "agent-1",
        )
        assert "REG_SHO_NO_LOCATE" not in result.violations


class TestSuspiciousRouting:
    """BSA / AML — Layering / structuring language in routing note triggers SAR review."""

    def setup_method(self):
        self.adapter = _make_adapter("suspicious_routing.yaml")

    @pytest.mark.parametrize("routing_note", [
        "layered through shell",
        "evading reporting",
        "shell company intermediary",
        "smurfing operation",
        "structuring to avoid CTR",
        "offshore_pass account",
        "intermediary obfuscation",
    ])
    def test_flags_suspicious_routing_note(self, routing_note: str):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"recipient_id": "BANK-X", "amount": 9000, "routing_note": routing_note},
            {},
            "agent-1",
        )
        assert "SUSPICIOUS_ROUTING" in result.violations

    def test_passes_clean_routing_note(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {"recipient_id": "BANK-X", "amount": 9000, "routing_note": "standard payroll transfer"},
            {},
            "agent-1",
        )
        assert "SUSPICIOUS_ROUTING" not in result.violations


# ===========================================================================
# 7. CROSS-RULE INTEGRATION — multiple rules firing together
# ===========================================================================


class TestMultipleRuleViolations:
    """Verify that multiple rules can fire simultaneously on one request."""

    def setup_method(self):
        self.adapter = _make_adapter(
            "finra_kyc_2090.yaml",
            "finra_rule_3110.yaml",
            "finra_rule_2010.yaml",
        )

    def test_kyc_and_wire_threshold_both_fire(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            # Missing customer_id (KYC) + over threshold (3110)
            {"account_id": "A1", "amount": 2_000_000},
            {},
            "agent-1",
        )
        assert "KYC_MISSING_FIELDS" in result.violations
        assert "SUPERVISION_WIRE_THRESHOLD_EXCEEDED" in result.violations

    def test_all_three_rules_fire(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {
                "account_id": "A1",
                "amount": 2_000_000,
                "memo": "fictitious wash trade",
            },
            {},
            "agent-1",
        )
        assert "KYC_MISSING_FIELDS" in result.violations
        assert "SUPERVISION_WIRE_THRESHOLD_EXCEEDED" in result.violations
        assert "COMMERCIAL_HONOR_VIOLATION" in result.violations

    def test_clean_request_passes_all_rules(self):
        result = self.adapter.evaluate(
            "wire_transfer",
            {
                "customer_id": "CUST-001",
                "account_id": "ACC-001",
                "amount": 50_000,
                "memo": "quarterly vendor payment",
                "agent_id": "registered-agent-001",
            },
            {},
            "registered-agent-001",
        )
        assert result.approved is True
        assert result.violations == []
