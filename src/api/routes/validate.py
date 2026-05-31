from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

import src.engine.audit_log as audit_log
from src.engine.audit_log import AuditEntry, compute_context_hash
from src.rules.models import RuleResult

logger = logging.getLogger(__name__)
router = APIRouter()


class ValidateRequest(BaseModel):
    """Inbound validation request from an AI agent.

    Attributes:
        action_type: Category of action the agent is attempting (e.g. ``"wire_transfer"``).
        parameters: Action-specific payload fields used by rule evaluators.
        context: Ambient metadata (session info, account metadata) available to rules.
        agent_id: Identifier of the requesting agent — recorded in the audit log.
    """

    action_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    agent_id: str


class ViolationDetail(BaseModel):
    """Details of a single rule violation.

    Attributes:
        rule_id: ID of the rule that was violated.
        violation_code: Short machine-readable code (e.g. ``OFAC_SANCTIONS_MATCH``).
        rationale: Human-readable explanation suitable for audit reports.
    """

    rule_id: str
    violation_code: str
    rationale: str


class ValidateResponse(BaseModel):
    """Validation outcome returned to the calling agent.

    Attributes:
        request_id: UUID for correlating this response with audit log entries.
        approved: ``True`` if all rules passed.
        violations: List of rule violations (empty when ``approved`` is ``True``).
        rationale: Summary rationale covering all violations.
        outcome: Enforcement outcome — approved, hard_block, soft_hold, or flagged.
        latency_ms: Total validation latency in milliseconds.
        audit_entry_id: entry_id of the written audit log record.
    """

    request_id: str
    approved: bool
    violations: list[ViolationDetail]
    rationale: str
    outcome: str
    latency_ms: float
    audit_entry_id: str


def _build_severity_maps(rules: list) -> tuple[set[str], set[str]]:
    """Build soft_hold and flag code sets from loaded rule definitions."""
    from src.rules.models import Severity
    soft_hold: set[str] = set()
    flag: set[str] = set()
    for rule in rules:
        sev = getattr(rule, "severity", None)
        if sev == Severity.soft_hold:
            soft_hold.add(rule.violation_code)
        elif sev == Severity.flag:
            flag.add(rule.violation_code)
    return soft_hold, flag


def _derive_outcome(
    approved: bool,
    violations: list[ViolationDetail],
    soft_hold_codes: set[str],
    flag_codes: set[str],
) -> str:
    """Map evaluation result to a canonical outcome string using live rule severity."""
    if approved:
        return "approved"
    codes = {v.violation_code for v in violations}
    if codes <= flag_codes:
        return "flagged"
    if codes <= (soft_hold_codes | flag_codes):
        return "soft_hold"
    return "hard_block"


@router.post("/validate", response_model=ValidateResponse, summary="Validate an agent action")
async def validate(req: ValidateRequest, request: Request) -> ValidateResponse:
    """Intercept an agent action, evaluate all compliance rules, and return an outcome.

    All requests — approved and blocked — are written to the immutable audit log.
    If the audit log write fails, the validation result is still returned and the
    failure is logged for manual reconciliation; the audit system never blocks a
    legitimate action.

    Args:
        req: The validation request body.
        request: FastAPI request object used to access application state.

    Returns:
        :class:`ValidateResponse` with the decision, violations, outcome,
        latency, and the audit_entry_id for traceability.
    """
    t0 = time.perf_counter()
    request_id = str(uuid.uuid4())

    governance = request.app.state.governance
    rules = request.app.state.rules
    soft_hold_codes, flag_codes = _build_severity_maps(rules)

    results: list[RuleResult] = governance.evaluate(
        req.action_type, req.parameters, req.context, req.agent_id
    )

    failures = [r for r in results if not r.passed]
    # flag-severity violations are recorded but do not block approval
    blocking_failures = [
        r for r in failures
        if (r.violation_code or "") not in flag_codes
    ]
    approved = len(blocking_failures) == 0

    violations = [
        ViolationDetail(
            rule_id=r.rule_id,
            violation_code=r.violation_code or "",
            rationale=r.rationale,
        )
        for r in failures
    ]

    if approved:
        rationale = "All rules passed."
    else:
        codes = ", ".join(v.violation_code for v in violations)
        rationale = f"Blocked by rule violations: {codes}."

    outcome = _derive_outcome(approved, violations, soft_hold_codes, flag_codes)
    latency_ms = (time.perf_counter() - t0) * 1000

    logger.info(
        "validate request_id=%s agent=%s action=%s outcome=%s latency_ms=%.2f",
        request_id, req.agent_id, req.action_type, outcome, latency_ms,
    )

    policy_set = getattr(request.app.state, "policy_set", "")
    audit_entry_id = ""
    try:
        audit_entry_id = await audit_log.write_entry(
            AuditEntry(
                agent_id=req.agent_id,
                action_type=req.action_type,
                parameters=json.dumps(req.parameters, sort_keys=True),
                context_hash=compute_context_hash(req.context),
                policy_set=policy_set,
                violations=json.dumps([v.model_dump() for v in violations], sort_keys=True),
                rationale=rationale,
                outcome=outcome,
                latency_ms=int(latency_ms),
            ),
            db_path=audit_log.DB_PATH,
        )
    except Exception:
        # Audit failure must never block a legitimate action — log for reconciliation.
        logger.exception(
            "AUDIT_WRITE_FAILURE request_id=%s agent=%s — result returned but not logged",
            request_id, req.agent_id,
        )

    return ValidateResponse(
        request_id=request_id,
        approved=approved,
        violations=violations,
        rationale=rationale,
        outcome=outcome,
        latency_ms=round(latency_ms, 3),
        audit_entry_id=audit_entry_id,
    )


# ---------------------------------------------------------------------------
# Payment gateway response handler
# ---------------------------------------------------------------------------

# Codes that require an immediate SAR escalation referral
_SAR_CODES: frozenset[str] = frozenset({
    "GATEWAY_FRAUD_DECLINE",
    "GATEWAY_CARD_RESTRICTED",
    "GATEWAY_LIMIT_EXCEEDED",
    "GATEWAY_INSUFFICIENT_FUNDS",
})

# Codes that permit a supervised retry (system errors only)
_RETRY_PERMITTED_CODES: frozenset[str] = frozenset({
    "GATEWAY_SYSTEM_ERROR",
})


class GatewayResponseRequest(BaseModel):
    """Inbound gateway response submitted by an AI agent for compliance triage.

    Attributes:
        action_type: The action that was attempted (e.g. ``"wire_transfer"``).
        gateway_response_code: Raw response code returned by the payment gateway.
        agent_id: Identifier of the agent that attempted the action.
        parameters: Original action parameters — used for audit context.
        context: Ambient metadata (account info, session, etc.).
    """

    action_type: str
    gateway_response_code: str
    agent_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class GatewayResponseResult(BaseModel):
    """Compliance triage result for a payment gateway decline.

    Attributes:
        request_id: UUID for correlation with audit log.
        gateway_response_code: The code that was evaluated.
        violation_codes: List of compliance violation codes triggered.
        outcome: Enforcement outcome — approved, hard_block, soft_hold, or flagged.
        retry_permitted: Whether the agent may retry the transaction autonomously.
        escalate_to_compliance: Whether the compliance desk must be notified.
        sar_review_required: Whether a SAR filing review is warranted.
        rationale: Human-readable compliance guidance for the agent.
        latency_ms: Evaluation latency in milliseconds.
        audit_entry_id: Audit log entry ID for this gateway response event.
    """

    request_id: str
    gateway_response_code: str
    violation_codes: list[str]
    outcome: str
    retry_permitted: bool
    escalate_to_compliance: bool
    sar_review_required: bool
    rationale: str
    latency_ms: float
    audit_entry_id: str


@router.post(
    "/validate/gateway-response",
    response_model=GatewayResponseResult,
    summary="Evaluate a payment gateway decline code for compliance action",
)
async def validate_gateway_response(
    req: GatewayResponseRequest,
    request: Request,
) -> GatewayResponseResult:
    """Triage a payment gateway decline code and return compliance guidance.

    Called by an AI agent after receiving a decline from a payment processor.
    Evaluates the gateway response code against the loaded gateway rule pack,
    determines whether the agent may retry, whether the compliance desk must
    be notified, and whether a SAR filing review is warranted.

    All gateway response events are written to the immutable audit log.

    Args:
        req: The gateway response triage request.
        request: FastAPI request object used to access application state.

    Returns:
        :class:`GatewayResponseResult` with outcome, retry guidance,
        escalation flags, and the audit entry ID.
    """
    t0 = time.perf_counter()
    request_id = str(uuid.uuid4())

    # Inject the gateway response code into parameters so pattern-match rules can read it
    enriched_params = {**req.parameters, "gateway_response_code": req.gateway_response_code}

    governance = request.app.state.governance
    rules = request.app.state.rules
    soft_hold_codes, flag_codes = _build_severity_maps(rules)

    results: list[RuleResult] = governance.evaluate(
        req.action_type, enriched_params, req.context, req.agent_id
    )

    failures = [r for r in results if not r.passed]
    blocking_failures = [r for r in failures if (r.violation_code or "") not in flag_codes]
    approved = len(blocking_failures) == 0

    violations = [
        ViolationDetail(
            rule_id=r.rule_id,
            violation_code=r.violation_code or "",
            rationale=r.rationale,
        )
        for r in failures
    ]
    violation_codes = [v.violation_code for v in violations]

    outcome = _derive_outcome(approved, violations, soft_hold_codes, flag_codes)

    # Derive compliance guidance flags
    sar_review_required = bool(_SAR_CODES & set(violation_codes))
    retry_permitted = (
        bool(_RETRY_PERMITTED_CODES & set(violation_codes))
        and not (set(violation_codes) - _RETRY_PERMITTED_CODES)
    )
    escalate_to_compliance = outcome in ("hard_block", "soft_hold")

    if not violation_codes:
        rationale = (
            f"Gateway code '{req.gateway_response_code}' does not match any compliance rule. "
            "No action required."
        )
    else:
        parts = []
        if sar_review_required:
            parts.append("SAR filing review required.")
        if escalate_to_compliance:
            parts.append("Escalate to compliance desk.")
        if retry_permitted:
            parts.append("Supervised retry permitted after ops desk clearance.")
        else:
            parts.append("Autonomous retry not permitted.")
        rationale = f"Gateway code '{req.gateway_response_code}' triggered: {', '.join(violation_codes)}. " + " ".join(parts)

    latency_ms = (time.perf_counter() - t0) * 1000

    logger.info(
        "gateway-response request_id=%s agent=%s action=%s code=%s outcome=%s",
        request_id, req.agent_id, req.action_type, req.gateway_response_code, outcome,
    )

    policy_set = getattr(request.app.state, "policy_set", "")
    audit_entry_id = ""
    try:
        audit_entry_id = await audit_log.write_entry(
            AuditEntry(
                agent_id=req.agent_id,
                action_type=req.action_type,
                parameters=json.dumps(enriched_params, sort_keys=True),
                context_hash=compute_context_hash(req.context),
                policy_set=policy_set,
                violations=json.dumps([v.model_dump() for v in violations], sort_keys=True),
                rationale=rationale,
                outcome=outcome,
                latency_ms=int(latency_ms),
            ),
            db_path=audit_log.DB_PATH,
        )
    except Exception:
        logger.exception(
            "AUDIT_WRITE_FAILURE request_id=%s — gateway response not logged", request_id
        )

    return GatewayResponseResult(
        request_id=request_id,
        gateway_response_code=req.gateway_response_code,
        violation_codes=violation_codes,
        outcome=outcome,
        retry_permitted=retry_permitted,
        escalate_to_compliance=escalate_to_compliance,
        sar_review_required=sar_review_required,
        rationale=rationale,
        latency_ms=round(latency_ms, 3),
        audit_entry_id=audit_entry_id,
    )
