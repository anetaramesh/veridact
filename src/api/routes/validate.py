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


def _derive_outcome(approved: bool, violations: list[ViolationDetail]) -> str:
    """Map evaluation result to a canonical outcome string.

    Without per-rule severity info in RuleResult, infer severity from known
    violation codes, defaulting to hard_block for unknown codes.
    """
    if approved:
        return "approved"
    codes = {v.violation_code for v in violations}
    _soft_hold_codes = {"WIRE_THRESHOLD_EXCEEDED"}
    _flag_codes: set[str] = set()

    if codes <= _flag_codes:
        return "flagged"
    if codes <= _soft_hold_codes:
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
    results: list[RuleResult] = governance.evaluate(
        req.action_type, req.parameters, req.context, req.agent_id
    )

    failures = [r for r in results if not r.passed]
    approved = len(failures) == 0

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

    outcome = _derive_outcome(approved, violations)
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
