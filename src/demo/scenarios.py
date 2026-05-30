"""Veridact demo scenario runner.

Fires 25 sequential POST /validate requests against a running Veridact server,
simulating realistic financial-services workflows and printing a live result table.

Usage::

    python -m src.demo --scenario treasury
    python -m src.demo --scenario loan
    python -m src.demo --scenario trading
    python -m src.demo --scenario treasury --base-url http://localhost:8000
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

def _treasury_actions() -> list[dict[str, Any]]:
    """25 wire-transfer requests covering normal, OFAC-blocked, threshold-held, and suspicious-routing cases."""
    actions: list[dict[str, Any]] = []

    # 14 normal wire transfers $50k–$800k — should approve
    normal_pairs = [
        ("CORP-A", "CORP-001", 50_000),
        ("CORP-A", "CORP-002", 125_000),
        ("CORP-A", "CORP-003", 200_000),
        ("CORP-A", "CORP-004", 75_000),
        ("CORP-B", "CORP-005", 310_000),
        ("CORP-B", "CORP-006", 450_000),
        ("CORP-B", "CORP-007", 88_000),
        ("CORP-B", "CORP-008", 620_000),
        ("CORP-C", "CORP-009", 390_000),
        ("CORP-C", "CORP-010", 800_000),
        ("CORP-C", "CORP-011", 55_000),
        ("CORP-C", "CORP-012", 175_000),
        ("CORP-D", "CORP-013", 500_000),
        ("CORP-D", "CORP-014", 230_000),
    ]
    for account_id, recipient_id, amount in normal_pairs:
        actions.append({
            "action_type": "wire_transfer",
            "agent_id": "treasury-agent-v1",
            "parameters": {"amount": amount, "recipient_id": recipient_id, "currency": "USD"},
            "context": {"account_id": account_id, "routing_note": "standard_wire"},
        })

    # 4 transfers to OFAC-flagged recipients — hard block
    for sdn in ["SDN-001", "SDN-002", "SDN-003", "BLOCKED-ENTITY-A"]:
        actions.append({
            "action_type": "wire_transfer",
            "agent_id": "treasury-agent-v1",
            "parameters": {"amount": 250_000, "recipient_id": sdn, "currency": "USD"},
            "context": {"account_id": "CORP-A", "routing_note": "standard_wire"},
        })

    # 3 transfers > $1M threshold — soft hold (WIRE_THRESHOLD_EXCEEDED)
    for amount in [1_100_000, 1_500_000, 2_000_000]:
        actions.append({
            "action_type": "wire_transfer",
            "agent_id": "treasury-agent-v1",
            "parameters": {"amount": amount, "recipient_id": "CORP-015", "currency": "USD"},
            "context": {"account_id": "CORP-D", "routing_note": "large_wire_approval_pending"},
        })

    # 4 suspicious routing transfers (evasion context) — soft hold (SUSPICIOUS_ROUTING)
    evasion_notes = [
        "layered_transfer_offshore_pass",
        "shell_intermediary_route",
        "structuring_avoid_threshold",
        "smurfing_split_wire",
    ]
    for note in evasion_notes:
        actions.append({
            "action_type": "wire_transfer",
            "agent_id": "treasury-agent-v1",
            "parameters": {"amount": 49_000, "recipient_id": "CORP-016", "currency": "USD"},
            "context": {"account_id": "CORP-E", "routing_note": note},
        })

    return actions


def _loan_actions() -> list[dict[str, Any]]:
    """25 loan-decision requests covering normal, geographic-concentration, and adverse-action cases."""
    actions: list[dict[str, Any]] = []

    # 16 normal loan decisions — approve
    for i in range(1, 17):
        actions.append({
            "action_type": "loan_decision",
            "agent_id": "loan-agent-v1",
            "parameters": {
                "applicant_id": f"APPL-{i:03d}",
                "loan_amount": 150_000 + i * 10_000,
                "credit_score": 680 + i,
                "decision": "approved",
            },
            "context": {
                "account_id": f"LOAN-ACC-{i:03d}",
                "geographic_flag": "normal",
                "adverse_action_flag": "compliant",
            },
        })

    # 5 decisions with geographic concentration pattern — soft hold
    geo_flags = [
        "concentrated_single_tract",
        "redline_risk_zone",
        "cra_gap_area",
        "single_tract_overdense",
        "concentrated_zip_cluster",
    ]
    for flag in geo_flags:
        actions.append({
            "action_type": "loan_decision",
            "agent_id": "loan-agent-v1",
            "parameters": {
                "applicant_id": f"APPL-GEO-{flag[:6]}",
                "loan_amount": 200_000,
                "credit_score": 720,
                "decision": "approved",
            },
            "context": {
                "account_id": "LOAN-ACC-GEO",
                "geographic_flag": flag,
                "adverse_action_flag": "compliant",
            },
        })

    # 4 decisions with adverse action notice issues — soft hold
    notice_flags = [
        "missing_notice",
        "incomplete_notice",
        "no_notice",
        "notice_defect_missing_reason",
    ]
    for flag in notice_flags:
        actions.append({
            "action_type": "loan_decision",
            "agent_id": "loan-agent-v1",
            "parameters": {
                "applicant_id": f"APPL-ADV-{flag[:6]}",
                "loan_amount": 180_000,
                "credit_score": 580,
                "decision": "denied",
            },
            "context": {
                "account_id": "LOAN-ACC-ADV",
                "geographic_flag": "normal",
                "adverse_action_flag": flag,
            },
        })

    return actions


def _trading_actions() -> list[dict[str, Any]]:
    """25 trade-order requests covering normal, Reg-SHO-blocked, and MNPI-held cases."""
    actions: list[dict[str, Any]] = []

    # 15 normal trade orders — approve
    tickers = ["AAPL", "MSFT", "GOOG", "JPM", "GS", "BAC", "WFC", "C", "MS", "BLK",
               "SCHW", "TDA", "IBKR", "CME", "ICE"]
    for i, ticker in enumerate(tickers):
        actions.append({
            "action_type": "trade_order",
            "agent_id": "trading-agent-v1",
            "parameters": {
                "ticker": ticker,
                "side": "buy",
                "quantity": 100 * (i + 1),
                "order_type": "limit",
                "locate_confirmed": "true",
            },
            "context": {
                "account_id": f"TRADE-ACC-{i+1:03d}",
                "mnpi_flag": "clean",
            },
        })

    # 5 short-sell orders without locate — hard block (REG_SHO_NO_LOCATE)
    short_tickers = ["GME", "AMC", "BBBY", "SPCE", "RIDE"]
    for ticker in short_tickers:
        actions.append({
            "action_type": "trade_order",
            "agent_id": "trading-agent-v1",
            "parameters": {
                "ticker": ticker,
                "side": "short_sell",
                "quantity": 500,
                "order_type": "market",
                "locate_confirmed": "false",
            },
            "context": {
                "account_id": "TRADE-ACC-SHORT",
                "mnpi_flag": "clean",
            },
        })

    # 5 orders with potential MNPI context — note: triggers if a rule exists;
    # with current rule packs these will approve; MNPI would be caught by semantic layer
    mnpi_context = [
        "insider_tip_unverified",
        "board_member_relative",
        "pre_announcement_period",
        "material_nonpublic_possible",
        "blackout_window_active",
    ]
    for ctx in mnpi_context:
        actions.append({
            "action_type": "trade_order",
            "agent_id": "trading-agent-v1",
            "parameters": {
                "ticker": "XYZ",
                "side": "buy",
                "quantity": 1000,
                "order_type": "market",
                "locate_confirmed": "true",
            },
            "context": {
                "account_id": "TRADE-ACC-MNPI",
                "mnpi_flag": ctx,
            },
        })

    return actions


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_SCENARIOS: dict[str, Any] = {
    "treasury": _treasury_actions,
    "loan": _loan_actions,
    "trading": _trading_actions,
}

_OUTCOME_LABELS = {
    "approved": "APPROVED  ",
    "hard_block": "HARD BLOCK",
    "soft_hold": "SOFT HOLD ",
    "flagged": "FLAGGED   ",
}

_OUTCOME_COLORS = {
    "approved": "\033[92m",
    "hard_block": "\033[91m",
    "soft_hold": "\033[93m",
    "flagged": "\033[94m",
}
_RESET = "\033[0m"


def _color(outcome: str, text: str) -> str:
    """Wrap text in ANSI color for the given outcome."""
    return f"{_OUTCOME_COLORS.get(outcome, '')}{text}{_RESET}"


def run_scenario(scenario: str, base_url: str, delay: float = 1.0) -> None:
    """Fire all 25 actions for *scenario* against *base_url* and print results.

    Args:
        scenario: One of treasury, loan, trading.
        base_url: Base URL of the running Veridact server.
        delay: Seconds to wait between requests (default 1.0).
    """
    actions = _SCENARIOS[scenario]()
    print(f"\n{'='*72}")
    print(f"  Veridact Demo — {scenario.upper()} scenario  ({len(actions)} actions)")
    print(f"  Server: {base_url}")
    print(f"{'='*72}")
    print(f"  {'#':>3}  {'Outcome':<12}  {'Action':<20}  {'Latency':>9}  {'Rationale'}")
    print(f"  {'-'*3}  {'-'*12}  {'-'*20}  {'-'*9}  {'-'*30}")

    totals: dict[str, int] = {"approved": 0, "hard_block": 0, "soft_hold": 0, "flagged": 0}

    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        for i, action in enumerate(actions, 1):
            try:
                resp = client.post("/validate", json=action)
                resp.raise_for_status()
                data = resp.json()
                outcome = data.get("outcome", "unknown")
                latency = data.get("latency_ms", 0.0)
                rationale = data.get("rationale", "")[:50]
                label = _OUTCOME_LABELS.get(outcome, outcome.upper()[:10])
                print(f"  {i:>3}  {_color(outcome, label):<22}  {action['action_type']:<20}  {latency:>7.1f}ms  {rationale}")
                totals[outcome] = totals.get(outcome, 0) + 1
            except httpx.HTTPStatusError as exc:
                print(f"  {i:>3}  HTTP {exc.response.status_code:<9}  {action['action_type']:<20}  {'—':>9}  Request failed")
            except httpx.RequestError as exc:
                print(f"  {i:>3}  ERROR       {action['action_type']:<20}  {'—':>9}  {exc}")
                print("\n  [!] Cannot reach server. Is `make serve` running?\n")
                sys.exit(1)

            if i < len(actions):
                time.sleep(delay)

    print(f"\n{'─'*72}")
    print("  Summary:")
    for outcome, count in totals.items():
        if count:
            print(f"    {_color(outcome, _OUTCOME_LABELS.get(outcome, outcome))}: {count}")
    print(f"{'='*72}\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    """Parse CLI arguments and run the selected scenario."""
    parser = argparse.ArgumentParser(
        prog="python -m src.demo",
        description="Veridact demo scenario runner",
    )
    parser.add_argument(
        "--scenario",
        choices=list(_SCENARIOS.keys()),
        required=True,
        help="Scenario to run: treasury | loan | trading",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the Veridact server (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds between requests (default: 1.0)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    run_scenario(args.scenario, args.base_url, args.delay)


if __name__ == "__main__":
    main()
