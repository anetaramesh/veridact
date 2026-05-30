# Veridact — Agentic AI Liability Auditor

## Product
Real-time compliance middleware for autonomous AI agents in financial services.
Sits between an AI agent's decision and the downstream financial system.
Intercepts, validates, blocks violations, and produces legal-grade audit logs.

## Stack decisions (do not change without discussing)
- Backend: Python 3.11 + FastAPI + uvicorn
- Enforcement engine: Microsoft Agent Governance Toolkit (agent-os PyPI package)
- Rule packs: YAML files in /rules — human-readable, lawyer-reviewable
- Audit log: append-only SQLite (MVP) → ClickHouse (production)
- Audit chain: SHA-256 linked — each entry hashes the previous entry
- Frontend: React 18 + Vite + Tailwind CSS
- PDF reports: WeasyPrint
- Testing: pytest with 90%+ coverage target

## Architecture principle
Veridact is a MIDDLEWARE LAYER only. It never reads from or writes to
downstream financial systems. It intercepts the agent's outbound call,
validates it, and returns approved/blocked. Keep this separation absolute.

## Security rules
- Never log API keys, passwords, or raw financial account numbers
- Audit log entries are IMMUTABLE — no update or delete operations allowed
- All secrets via environment variables, never hardcoded

## Code standards
- Type hints on ALL functions and methods
- Docstrings on all public classes and methods
- Every public function has at least one pytest test
- Run pytest before every commit — all tests must pass
- No print() statements in production code — use Python logging module

## Regulatory accuracy
- Rule YAML files must cite the specific regulation and section they implement
- Any rule claiming to implement FINRA/SEC/CFPB regulation needs a comment
  with the exact rule reference (e.g. "FINRA Rule 3110(a)")
- Do NOT invent regulatory interpretations — flag for regulatory counsel review
