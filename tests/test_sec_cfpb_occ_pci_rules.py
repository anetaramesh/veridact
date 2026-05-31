"""Tests for SEC, CFPB, OCC/Fed, and PCI DSS compliance rule YAML files.

SEC rules:
  - sec_reg_fd_disclosure      (hard_block: MNPI / selective disclosure in memo)
  - sec_insider_trading        (hard_block: insider-prefix agent_id)
  - sec_reg_nms_best_execution (flag: missing order_routing_ref / best_execution_ref)
  - sec_volcker_rule           (hard_block: proprietary trading memo keywords)
  - sec_custody_rule           (flag: missing qualified_custodian_ref)

CFPB rules:
  - cfpb_tila_apr_disclosure        (hard_block: missing APR disclosure refs)
  - cfpb_respa_settlement           (flag: missing Loan Estimate / Closing Disclosure)
  - cfpb_udaap                      (hard_block: UDAAP keywords in memo)
  - cfpb_fcra_permissible_purpose   (hard_block: missing credit pull consent ref)
  - cfpb_ecoa_credit_decision       (hard_block: missing non-discrimination attestation)

OCC / Federal Reserve rules:
  - occ_reg_e_authorization         (hard_block: missing eft_authorization_ref)
  - occ_reg_cc_hold_period          (flag: hold_days > 5)
  - occ_reg_o_insider_lending       (soft_hold: insider_loan_amount > $100,000)
  - occ_reg_w_affiliate_transactions(soft_hold: affiliate keywords in memo)

PCI DSS rules:
  - pci_dss_pan_prohibited          (hard_block: raw PAN in memo)
  - pci_dss_cvv_prohibited          (hard_block: CVV value in memo)
  - pci_dss_tokenization_required   (flag: missing payment_token_ref)
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from httpx import AsyncClient

RULES_DIR = Path(__file__).parent.parent / "rules"


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
# SEC — Regulation FD (Selective Disclosure)
# ===========================================================================

class TestSECRegFD:
    """MNPI / selective disclosure keywords in memo → hard_block."""

    def setup_method(self):
        self.adapter = _adapter("sec_reg_fd_disclosure.yaml")

    @pytest.mark.parametrize("memo", [
        "material non-public information transfer",
        "MNPI-based trade",
        "selective disclosure to preferred investors",
        "earnings preview shared with hedge fund",
        "undisclosed merger consideration",
        "guidance leak before announcement",
        "pre-announcement insider allocation",
        "front-run the earnings release",
        "non-public info confirmed",
    ])
    def test_blocks_mnpi_memo(self, memo: str):
        result = _eval(self.adapter, "equity_trade", {"memo": memo, "customer_id": "C1", "account_id": "A1"})
        assert "SEC_REG_FD_VIOLATION" in result.violations
        assert result.approved is False

    def test_passes_clean_memo(self):
        result = _eval(self.adapter, "equity_trade", {"memo": "standard market order Q2", "customer_id": "C1", "account_id": "A1"})
        assert "SEC_REG_FD_VIOLATION" not in result.violations

    @pytest.mark.parametrize("action", ["equity_trade", "loan_decision"])
    def test_applies_to_covered_action_types(self, action: str):
        result = _eval(self.adapter, action, {"memo": "MNPI trade execution"})
        assert "SEC_REG_FD_VIOLATION" in result.violations

    def test_does_not_apply_to_wire_transfer(self):
        result = _eval(self.adapter, "wire_transfer", {"memo": "MNPI trade", "amount": 5000})
        assert "SEC_REG_FD_VIOLATION" not in result.violations

    def test_case_insensitive_match(self):
        result = _eval(self.adapter, "equity_trade", {"memo": "mnpi based decision"})
        assert "SEC_REG_FD_VIOLATION" in result.violations


# ===========================================================================
# SEC — Insider Trading (Rule 10b-5)
# ===========================================================================

class TestSECInsiderTrading:
    """Insider-prefix agent IDs → hard_block on equity_trade."""

    def setup_method(self):
        self.adapter = _adapter("sec_insider_trading.yaml")

    @pytest.mark.parametrize("agent_id", [
        "INSIDER-officer-001",
        "BLACKOUT-period-agent",
        "RESTRICTED-PERIOD-trader",
        "10b5-PLAN-BREACH-agent",
        "TIPPEE-hedge-fund",
    ])
    def test_blocks_insider_agent(self, agent_id: str):
        # Rule uses field: agent_id — must be in parameters dict, not just audit arg
        result = _eval(self.adapter, "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "agent_id": agent_id}, agent_id=agent_id)
        assert "SEC_INSIDER_TRADING" in result.violations
        assert result.approved is False

    def test_passes_clean_agent(self):
        result = _eval(self.adapter, "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "agent_id": "trading-desk-001"})
        assert "SEC_INSIDER_TRADING" not in result.violations

    def test_does_not_apply_to_wire_transfer(self):
        result = _eval(self.adapter, "wire_transfer",
            {"amount": 5000, "agent_id": "INSIDER-officer-001"})
        assert "SEC_INSIDER_TRADING" not in result.violations

    def test_case_insensitive_insider_prefix(self):
        result = _eval(self.adapter, "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "agent_id": "insider-agent"})
        assert "SEC_INSIDER_TRADING" in result.violations


# ===========================================================================
# SEC — Reg NMS Best Execution
# ===========================================================================

class TestSECRegNMS:
    """Missing order_routing_ref or best_execution_ref → flag (not block)."""

    def setup_method(self):
        self.adapter = _adapter("sec_reg_nms_best_execution.yaml")

    _FULL = {
        "customer_id": "C1", "account_id": "A1",
        "order_routing_ref": "ROUTE-2026-001",
        "best_execution_ref": "BESTEX-2026-001",
    }

    def test_flags_missing_order_routing_ref(self):
        params = {k: v for k, v in self._FULL.items() if k != "order_routing_ref"}
        result = _eval(self.adapter, "equity_trade", params)
        assert "SEC_BEST_EXECUTION_MISSING" in result.violations

    def test_flags_missing_best_execution_ref(self):
        params = {k: v for k, v in self._FULL.items() if k != "best_execution_ref"}
        result = _eval(self.adapter, "equity_trade", params)
        assert "SEC_BEST_EXECUTION_MISSING" in result.violations

    def test_passes_with_all_refs(self):
        result = _eval(self.adapter, "equity_trade", self._FULL)
        assert "SEC_BEST_EXECUTION_MISSING" not in result.violations

    def test_flag_severity_still_approves(self):
        params = {k: v for k, v in self._FULL.items() if k != "order_routing_ref"}
        result = _eval(self.adapter, "equity_trade", params)
        assert result.approved is True  # flag — not blocking

    def test_does_not_apply_to_wire_transfer(self):
        result = _eval(self.adapter, "wire_transfer", {"customer_id": "C1", "account_id": "A1"})
        assert "SEC_BEST_EXECUTION_MISSING" not in result.violations


# ===========================================================================
# SEC — Volcker Rule
# ===========================================================================

class TestSECVolckerRule:
    """Proprietary trading keywords in memo → hard_block."""

    def setup_method(self):
        self.adapter = _adapter("sec_volcker_rule.yaml")

    @pytest.mark.parametrize("memo", [
        "proprietary trading position",
        "prop desk allocation",
        "own account trading execution",
        "principal position accumulation",
        "short-term arbitrage profit",
        "trading book rebalance",
        "volcker exempt market making",
    ])
    def test_blocks_proprietary_trading_memo(self, memo: str):
        result = _eval(self.adapter, "equity_trade", {"memo": memo, "customer_id": "C1"})
        assert "SEC_VOLCKER_RULE_VIOLATION" in result.violations
        assert result.approved is False

    def test_passes_agency_trading_memo(self):
        result = _eval(self.adapter, "equity_trade", {"memo": "client agency order execution", "customer_id": "C1"})
        assert "SEC_VOLCKER_RULE_VIOLATION" not in result.violations

    def test_does_not_apply_to_wire_transfer(self):
        result = _eval(self.adapter, "wire_transfer", {"memo": "proprietary trading funds"})
        assert "SEC_VOLCKER_RULE_VIOLATION" not in result.violations

    def test_case_insensitive_proprietary(self):
        result = _eval(self.adapter, "equity_trade", {"memo": "PROPRIETARY TRADING DESK"})
        assert "SEC_VOLCKER_RULE_VIOLATION" in result.violations


# ===========================================================================
# SEC — Investment Adviser Custody Rule
# ===========================================================================

class TestSECCustodyRule:
    """Missing custody documentation → flag."""

    def setup_method(self):
        self.adapter = _adapter("sec_custody_rule.yaml")

    _FULL = {
        "customer_id": "C1", "account_id": "A1",
        "qualified_custodian_ref": "CUST-REF-001",
        "adviser_registration_ref": "RIA-SEC-001",
    }

    def test_flags_missing_custodian_ref(self):
        params = {k: v for k, v in self._FULL.items() if k != "qualified_custodian_ref"}
        result = _eval(self.adapter, "equity_trade", params)
        assert "SEC_CUSTODY_RULE_MISSING" in result.violations

    def test_flags_missing_adviser_ref(self):
        params = {k: v for k, v in self._FULL.items() if k != "adviser_registration_ref"}
        result = _eval(self.adapter, "equity_trade", params)
        assert "SEC_CUSTODY_RULE_MISSING" in result.violations

    def test_passes_with_all_refs(self):
        result = _eval(self.adapter, "equity_trade", self._FULL)
        assert "SEC_CUSTODY_RULE_MISSING" not in result.violations

    def test_flag_severity_approves(self):
        result = _eval(self.adapter, "account_open", {"customer_id": "C1", "account_id": "A1"})
        assert result.approved is True


# ===========================================================================
# CFPB — TILA APR Disclosure
# ===========================================================================

class TestCFPBTILADisclosure:
    """Missing APR / loan term / finance charge refs → hard_block."""

    def setup_method(self):
        self.adapter = _adapter("cfpb_tila_apr_disclosure.yaml")

    _FULL = {
        "customer_id": "C1", "account_id": "A1",
        "apr_disclosure_ref": "APR-2026-001",
        "loan_term_disclosure_ref": "TERM-2026-001",
        "finance_charge_ref": "FC-2026-001",
    }

    def test_passes_with_all_disclosures(self):
        result = _eval(self.adapter, "loan_decision", self._FULL)
        assert "CFPB_TILA_DISCLOSURE_MISSING" not in result.violations

    @pytest.mark.parametrize("missing", ["apr_disclosure_ref", "loan_term_disclosure_ref", "finance_charge_ref"])
    def test_blocks_when_field_missing(self, missing: str):
        params = {k: v for k, v in self._FULL.items() if k != missing}
        result = _eval(self.adapter, "loan_decision", params)
        assert "CFPB_TILA_DISCLOSURE_MISSING" in result.violations
        assert result.approved is False

    def test_does_not_apply_to_wire_transfer(self):
        result = _eval(self.adapter, "wire_transfer", {"customer_id": "C1", "account_id": "A1"})
        assert "CFPB_TILA_DISCLOSURE_MISSING" not in result.violations

    def test_empty_ref_triggers_block(self):
        params = {**self._FULL, "apr_disclosure_ref": ""}
        result = _eval(self.adapter, "loan_decision", params)
        assert "CFPB_TILA_DISCLOSURE_MISSING" in result.violations


# ===========================================================================
# CFPB — RESPA Settlement Disclosures
# ===========================================================================

class TestCFPBRESPA:
    """Missing Loan Estimate / Closing Disclosure refs → flag."""

    def setup_method(self):
        self.adapter = _adapter("cfpb_respa_settlement.yaml")

    _FULL = {
        "customer_id": "C1", "account_id": "A1",
        "loan_estimate_ref": "LE-2026-001",
        "closing_disclosure_ref": "CD-2026-001",
    }

    def test_passes_with_both_disclosures(self):
        result = _eval(self.adapter, "loan_decision", self._FULL)
        assert "CFPB_RESPA_DISCLOSURE_MISSING" not in result.violations

    def test_flags_missing_loan_estimate(self):
        params = {k: v for k, v in self._FULL.items() if k != "loan_estimate_ref"}
        result = _eval(self.adapter, "loan_decision", params)
        assert "CFPB_RESPA_DISCLOSURE_MISSING" in result.violations

    def test_flags_missing_closing_disclosure(self):
        params = {k: v for k, v in self._FULL.items() if k != "closing_disclosure_ref"}
        result = _eval(self.adapter, "loan_decision", params)
        assert "CFPB_RESPA_DISCLOSURE_MISSING" in result.violations

    def test_flag_severity_approves(self):
        result = _eval(self.adapter, "loan_decision", {"customer_id": "C1", "account_id": "A1"})
        assert result.approved is True  # flag

    def test_applies_to_account_open(self):
        result = _eval(self.adapter, "account_open", {"customer_id": "C1", "account_id": "A1"})
        assert "CFPB_RESPA_DISCLOSURE_MISSING" in result.violations


# ===========================================================================
# CFPB — UDAAP
# ===========================================================================

class TestCFPBUDAAP:
    """UDAAP keywords in memo → hard_block."""

    def setup_method(self):
        self.adapter = _adapter("cfpb_udaap.yaml")

    @pytest.mark.parametrize("memo", [
        "hidden fee structure",
        "undisclosed charge added",
        "misleading terms and conditions",
        "coercive lending terms",
        "bait and switch offer",
        "deceptive practice fee",
        "abusive term imposed",
        "excessive fee charged",
        "predatory lending product",
        "junk fee added",
        "gotcha clause triggered",
        "fine print trap activated",
        "confusing term embedded",
    ])
    def test_blocks_udaap_memo(self, memo: str):
        result = _eval(self.adapter, "loan_decision", {"memo": memo, "customer_id": "C1"})
        assert "CFPB_UDAAP_VIOLATION" in result.violations
        assert result.approved is False

    def test_passes_clean_memo(self):
        result = _eval(self.adapter, "loan_decision", {"memo": "standard personal loan disbursement"})
        assert "CFPB_UDAAP_VIOLATION" not in result.violations

    @pytest.mark.parametrize("action", ["wire_transfer", "ach_payment", "loan_decision", "account_open"])
    def test_applies_to_covered_action_types(self, action: str):
        result = _eval(self.adapter, action, {"memo": "hidden fee structure"})
        assert "CFPB_UDAAP_VIOLATION" in result.violations

    def test_case_insensitive_match(self):
        result = _eval(self.adapter, "loan_decision", {"memo": "HIDDEN FEE ADDED"})
        assert "CFPB_UDAAP_VIOLATION" in result.violations


# ===========================================================================
# CFPB — FCRA Permissible Purpose
# ===========================================================================

class TestCFPBFCRA:
    """Missing permissible purpose / credit consent refs → hard_block."""

    def setup_method(self):
        self.adapter = _adapter("cfpb_fcra_permissible_purpose.yaml")

    _FULL = {
        "customer_id": "C1", "account_id": "A1",
        "permissible_purpose_ref": "PP-CREDIT-2026-001",
        "credit_pull_consent_ref": "CONSENT-2026-001",
    }

    def test_passes_with_all_refs(self):
        result = _eval(self.adapter, "loan_decision", self._FULL)
        assert "CFPB_FCRA_PERMISSIBLE_PURPOSE_MISSING" not in result.violations

    @pytest.mark.parametrize("missing", ["permissible_purpose_ref", "credit_pull_consent_ref"])
    def test_blocks_when_missing(self, missing: str):
        params = {k: v for k, v in self._FULL.items() if k != missing}
        result = _eval(self.adapter, "loan_decision", params)
        assert "CFPB_FCRA_PERMISSIBLE_PURPOSE_MISSING" in result.violations
        assert result.approved is False

    def test_applies_to_account_open(self):
        result = _eval(self.adapter, "account_open", {"customer_id": "C1", "account_id": "A1"})
        assert "CFPB_FCRA_PERMISSIBLE_PURPOSE_MISSING" in result.violations


# ===========================================================================
# CFPB — ECOA Credit Decision
# ===========================================================================

class TestCFPBECOA:
    """Missing non-discrimination attestation → hard_block."""

    def setup_method(self):
        self.adapter = _adapter("cfpb_ecoa_credit_decision.yaml")

    _FULL = {
        "customer_id": "C1", "account_id": "A1",
        "credit_decision_basis_ref": "CDB-2026-001",
        "non_discrimination_attestation_ref": "NDA-2026-001",
    }

    def test_passes_with_all_refs(self):
        result = _eval(self.adapter, "loan_decision", self._FULL)
        assert "CFPB_ECOA_DOCUMENTATION_MISSING" not in result.violations

    @pytest.mark.parametrize("missing", ["credit_decision_basis_ref", "non_discrimination_attestation_ref"])
    def test_blocks_when_missing(self, missing: str):
        params = {k: v for k, v in self._FULL.items() if k != missing}
        result = _eval(self.adapter, "loan_decision", params)
        assert "CFPB_ECOA_DOCUMENTATION_MISSING" in result.violations
        assert result.approved is False

    def test_only_applies_to_loan_decision(self):
        result = _eval(self.adapter, "wire_transfer", {"customer_id": "C1", "account_id": "A1"})
        assert "CFPB_ECOA_DOCUMENTATION_MISSING" not in result.violations


# ===========================================================================
# OCC / Fed — Regulation E Authorization
# ===========================================================================

class TestOCCRegE:
    """Missing eft_authorization_ref → hard_block on EFTs."""

    def setup_method(self):
        self.adapter = _adapter("occ_reg_e_authorization.yaml")

    def test_blocks_missing_eft_auth_ref(self):
        result = _eval(self.adapter, "wire_transfer", {"customer_id": "C1", "account_id": "A1"})
        assert "OCC_REG_E_AUTHORIZATION_MISSING" in result.violations
        assert result.approved is False

    def test_passes_with_eft_auth_ref(self):
        result = _eval(self.adapter, "wire_transfer", {
            "customer_id": "C1", "account_id": "A1",
            "eft_authorization_ref": "EFT-AUTH-2026-001",
        })
        assert "OCC_REG_E_AUTHORIZATION_MISSING" not in result.violations

    @pytest.mark.parametrize("action", ["wire_transfer", "ach_payment", "internal_transfer"])
    def test_applies_to_covered_actions(self, action: str):
        result = _eval(self.adapter, action, {"customer_id": "C1", "account_id": "A1"})
        assert "OCC_REG_E_AUTHORIZATION_MISSING" in result.violations

    def test_does_not_apply_to_equity_trade(self):
        result = _eval(self.adapter, "equity_trade", {"customer_id": "C1", "account_id": "A1"})
        assert "OCC_REG_E_AUTHORIZATION_MISSING" not in result.violations


# ===========================================================================
# OCC / Fed — Regulation CC Hold Period
# ===========================================================================

class TestOCCRegCC:
    """hold_days > 5 → flag on check_issuance."""

    def setup_method(self):
        self.adapter = _adapter("occ_reg_cc_hold_period.yaml")

    def test_flags_hold_above_5_days(self):
        result = _eval(self.adapter, "check_issuance", {"hold_days": 6})
        assert "OCC_REG_CC_HOLD_EXCEEDED" in result.violations

    def test_passes_at_5_days(self):
        result = _eval(self.adapter, "check_issuance", {"hold_days": 5})
        assert "OCC_REG_CC_HOLD_EXCEEDED" not in result.violations

    def test_passes_below_5_days(self):
        result = _eval(self.adapter, "check_issuance", {"hold_days": 3})
        assert result.approved is True

    @pytest.mark.parametrize("days", [6, 7, 10, 30])
    def test_all_long_holds_flagged(self, days: int):
        result = _eval(self.adapter, "check_issuance", {"hold_days": days})
        assert "OCC_REG_CC_HOLD_EXCEEDED" in result.violations

    def test_flag_severity_approves(self):
        result = _eval(self.adapter, "check_issuance", {"hold_days": 10})
        assert result.approved is True  # flag, not block

    def test_does_not_apply_to_wire(self):
        result = _eval(self.adapter, "wire_transfer", {"hold_days": 30})
        assert "OCC_REG_CC_HOLD_EXCEEDED" not in result.violations


# ===========================================================================
# OCC / Fed — Regulation O Insider Lending
# ===========================================================================

class TestOCCRegO:
    """insider_loan_amount > $100,000 → soft_hold."""

    def setup_method(self):
        self.adapter = _adapter("occ_reg_o_insider_lending.yaml")

    def test_soft_holds_above_100k(self):
        result = _eval(self.adapter, "loan_decision", {"insider_loan_amount": 100001})
        assert "OCC_REG_O_INSIDER_LIMIT_EXCEEDED" in result.violations
        assert result.approved is False

    def test_passes_at_100k(self):
        result = _eval(self.adapter, "loan_decision", {"insider_loan_amount": 100000})
        assert "OCC_REG_O_INSIDER_LIMIT_EXCEEDED" not in result.violations

    def test_passes_below_100k(self):
        result = _eval(self.adapter, "loan_decision", {"insider_loan_amount": 50000})
        assert result.approved is True

    @pytest.mark.parametrize("amount", [100001, 250000, 1000000])
    def test_all_over_limit_amounts_trigger(self, amount: int):
        result = _eval(self.adapter, "loan_decision", {"insider_loan_amount": amount})
        assert "OCC_REG_O_INSIDER_LIMIT_EXCEEDED" in result.violations

    def test_does_not_apply_to_wire_transfer(self):
        result = _eval(self.adapter, "wire_transfer", {"insider_loan_amount": 500000})
        assert "OCC_REG_O_INSIDER_LIMIT_EXCEEDED" not in result.violations


# ===========================================================================
# OCC / Fed — Regulation W Affiliate Transactions
# ===========================================================================

class TestOCCRegW:
    """Affiliate keywords in memo → soft_hold."""

    def setup_method(self):
        self.adapter = _adapter("occ_reg_w_affiliate_transactions.yaml")

    @pytest.mark.parametrize("memo", [
        "affiliate transfer to subsidiary",
        "subsidiary payment processing",
        "parent company fund movement",
        "holding company capital injection",
        "related party transfer execution",
        "intra-group settlement",
        "intercompany payment",
        "reg w affiliate transaction",
    ])
    def test_soft_holds_affiliate_memo(self, memo: str):
        result = _eval(self.adapter, "wire_transfer", {"memo": memo})
        assert "OCC_REG_W_AFFILIATE_FLAG" in result.violations
        assert result.approved is False

    def test_passes_third_party_memo(self):
        result = _eval(self.adapter, "wire_transfer", {"memo": "vendor invoice payment"})
        assert "OCC_REG_W_AFFILIATE_FLAG" not in result.violations

    @pytest.mark.parametrize("action", ["wire_transfer", "ach_payment", "internal_transfer"])
    def test_applies_to_covered_actions(self, action: str):
        result = _eval(self.adapter, action, {"memo": "affiliate transfer"})
        assert "OCC_REG_W_AFFILIATE_FLAG" in result.violations

    def test_does_not_apply_to_equity_trade(self):
        result = _eval(self.adapter, "equity_trade", {"memo": "affiliate holding"})
        assert "OCC_REG_W_AFFILIATE_FLAG" not in result.violations


# ===========================================================================
# PCI DSS — PAN in Parameters
# ===========================================================================

class TestPCIDSSPAN:
    """Raw PAN (card number) in memo → hard_block."""

    def setup_method(self):
        self.adapter = _adapter("pci_dss_pan_prohibited.yaml")

    @pytest.mark.parametrize("memo", [
        "card 4532015112830366 payment",          # Visa 16-digit
        "payment 5425233430109903 processed",     # MC 16-digit
        "card: 4532-0151-1283-0366",              # Visa with dashes
        "ref 4532 0151 1283 0366 confirmed",      # Visa with spaces
        "amex 371449635398431 transaction",       # Amex 15-digit
        "discover 6011111111111117 payment",      # Discover 16-digit
        "mc 5425 2334 3010 9903 wire",            # MC with spaces
    ])
    def test_blocks_pan_in_memo(self, memo: str):
        result = _eval(self.adapter, "wire_transfer", {"memo": memo})
        assert "PCI_DSS_PAN_IN_PARAMETERS" in result.violations
        assert result.approved is False

    def test_passes_memo_without_pan(self):
        result = _eval(self.adapter, "wire_transfer", {"memo": "standard payroll wire ref 2026-001"})
        assert "PCI_DSS_PAN_IN_PARAMETERS" not in result.violations

    def test_passes_partial_masked_pan(self):
        result = _eval(self.adapter, "wire_transfer", {"memo": "card ending 3366 approved"})
        assert "PCI_DSS_PAN_IN_PARAMETERS" not in result.violations

    @pytest.mark.parametrize("action", ["wire_transfer", "ach_payment", "check_issuance", "internal_transfer"])
    def test_applies_to_covered_actions(self, action: str):
        result = _eval(self.adapter, action, {"memo": "card 4532015112830366 payment"})
        assert "PCI_DSS_PAN_IN_PARAMETERS" in result.violations


# ===========================================================================
# PCI DSS — CVV Prohibited
# ===========================================================================

class TestPCIDSSCVV:
    """CVV/CVC value in memo → hard_block."""

    def setup_method(self):
        self.adapter = _adapter("pci_dss_cvv_prohibited.yaml")

    @pytest.mark.parametrize("memo", [
        "cvv=123 payment confirmed",
        "cvv: 456 transaction",
        "cvc=789 wire",
        "cvc: 012 payment",
        "cvv2=345 authorised",
        "cvc2: 678 confirmed",
        "cid=9012 payment",
        "security code=123 ref",
        "card verification 456 confirmed",
    ])
    def test_blocks_cvv_in_memo(self, memo: str):
        result = _eval(self.adapter, "wire_transfer", {"memo": memo})
        assert "PCI_DSS_CVV_IN_PARAMETERS" in result.violations
        assert result.approved is False

    def test_passes_memo_without_cvv(self):
        result = _eval(self.adapter, "wire_transfer", {"memo": "monthly vendor payment ref 2026"})
        assert "PCI_DSS_CVV_IN_PARAMETERS" not in result.violations

    def test_passes_cvv_word_without_value(self):
        result = _eval(self.adapter, "wire_transfer", {"memo": "cvv verification passed"})
        assert "PCI_DSS_CVV_IN_PARAMETERS" not in result.violations

    def test_case_insensitive_cvv(self):
        result = _eval(self.adapter, "wire_transfer", {"memo": "CVV=999 payment"})
        assert "PCI_DSS_CVV_IN_PARAMETERS" in result.violations


# ===========================================================================
# PCI DSS — Tokenization Required
# ===========================================================================

class TestPCIDSSTokenization:
    """Missing payment_token_ref → flag."""

    def setup_method(self):
        self.adapter = _adapter("pci_dss_tokenization_required.yaml")

    def test_flags_missing_token_ref(self):
        result = _eval(self.adapter, "wire_transfer", {"customer_id": "C1", "account_id": "A1"})
        assert "PCI_DSS_TOKEN_MISSING" in result.violations

    def test_passes_with_token_ref(self):
        result = _eval(self.adapter, "wire_transfer", {
            "customer_id": "C1", "account_id": "A1",
            "payment_token_ref": "TOK-VISA-2026-001",
        })
        assert "PCI_DSS_TOKEN_MISSING" not in result.violations

    def test_flag_severity_approves(self):
        result = _eval(self.adapter, "wire_transfer", {"customer_id": "C1", "account_id": "A1"})
        assert result.approved is True  # flag, not block

    def test_applies_to_ach_payment(self):
        result = _eval(self.adapter, "ach_payment", {"customer_id": "C1", "account_id": "A1"})
        assert "PCI_DSS_TOKEN_MISSING" in result.violations

    def test_does_not_apply_to_equity_trade(self):
        result = _eval(self.adapter, "equity_trade", {"customer_id": "C1", "account_id": "A1"})
        assert "PCI_DSS_TOKEN_MISSING" not in result.violations


# ===========================================================================
# Cross-category integration
# ===========================================================================

class TestCrossRuleIntegration:
    """Multiple categories loaded together — verify isolation and combinations."""

    def setup_method(self):
        self.adapter = _adapter(
            "sec_reg_fd_disclosure.yaml", "sec_insider_trading.yaml",
            "cfpb_tila_apr_disclosure.yaml", "cfpb_udaap.yaml",
            "occ_reg_e_authorization.yaml", "occ_reg_o_insider_lending.yaml",
            "pci_dss_pan_prohibited.yaml", "pci_dss_cvv_prohibited.yaml",
        )

    def test_sec_and_cfpb_both_fire(self):
        """MNPI memo (SEC FD) + missing APR disclosure (CFPB TILA)."""
        result = _eval(self.adapter, "loan_decision", {
            "customer_id": "C1", "account_id": "A1",
            "memo": "MNPI-based loan approval",
        })
        assert "SEC_REG_FD_VIOLATION" in result.violations
        assert "CFPB_TILA_DISCLOSURE_MISSING" in result.violations

    def test_pci_pan_and_cvv_both_fire_on_memo(self):
        """Both PAN and CVV in same memo → both violations."""
        result = _eval(self.adapter, "wire_transfer", {
            "memo": "card 4532015112830366 cvv=123 transfer",
        })
        assert "PCI_DSS_PAN_IN_PARAMETERS" in result.violations
        assert "PCI_DSS_CVV_IN_PARAMETERS" in result.violations

    def test_clean_transaction_passes_all(self):
        result = _eval(self.adapter, "wire_transfer", {
            "customer_id": "C1", "account_id": "A1",
            "amount": 500,
            "memo": "vendor payment ref VND-2026-001",
            "eft_authorization_ref": "EFT-AUTH-001",
            "payment_token_ref": "TOK-001",
        })
        violations = [v for v in result.violations if v.startswith(("SEC_", "CFPB_", "OCC_", "PCI_"))]
        assert violations == []

    def test_insider_agent_on_equity_fires_sec(self):
        result = _eval(self.adapter, "equity_trade",
            {"customer_id": "C1", "account_id": "A1", "order_routing_ref": "R1",
             "best_execution_ref": "B1", "agent_id": "INSIDER-officer"},
            agent_id="INSIDER-officer")
        assert "SEC_INSIDER_TRADING" in result.violations

    def test_udaap_memo_and_missing_eft_both_fire(self):
        result = _eval(self.adapter, "wire_transfer", {
            "customer_id": "C1", "account_id": "A1",
            "memo": "hidden fee structure payment",
        })
        assert "CFPB_UDAAP_VIOLATION" in result.violations
        assert "OCC_REG_E_AUTHORIZATION_MISSING" in result.violations
