from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

RULES_DIR = Path(__file__).parent.parent.parent.parent / "rules"
ACTIVE_RULES_PATH = Path(__file__).parent.parent.parent.parent / "active_rules.json"
_SAFE_NAME = re.compile(r"^[a-z0-9_\-]+$")


def _load_active_ids() -> set[str] | None:
    """Return the set of active rule IDs, or None meaning 'all active'."""
    try:
        data = json.loads(ACTIVE_RULES_PATH.read_text())
        ids = data.get("active_rule_ids")
        return set(ids) if ids is not None else None
    except Exception:
        return None


def _save_active_ids(ids: set[str] | None) -> None:
    ACTIVE_RULES_PATH.write_text(
        json.dumps({"active_rule_ids": sorted(ids) if ids is not None else None}, indent=2)
    )

router = APIRouter(prefix="/rules", tags=["rules"])


class RuleSaveRequest(BaseModel):
    """Payload for creating or updating a YAML rule file."""

    filename: str
    content: dict[str, Any]


def _resolve(filename: str) -> Path:
    """Resolve filename to an absolute path inside RULES_DIR.

    Raises HTTPException 400 for unsafe names and 404 for missing files.
    """
    name = filename.removesuffix(".yaml")
    if not _SAFE_NAME.match(name):
        raise HTTPException(status_code=400, detail="Invalid filename — use lowercase letters, digits, underscores, hyphens only.")
    return RULES_DIR / f"{name}.yaml"


@router.get("", summary="List all YAML rule files")
async def list_rules() -> JSONResponse:
    """Return filenames of all .yaml files in the rules directory."""
    files = sorted(p.name for p in RULES_DIR.glob("*.yaml"))
    return JSONResponse(files)


@router.get("/active/status", summary="Get active rule IDs and applied status for all rules")
async def get_active_status(request: Request) -> JSONResponse:
    """Return a dict mapping each rule ID to its applied (True/False) status."""
    all_rules = getattr(request.app.state, "rules", [])
    active_ids = _load_active_ids()
    result = {}
    for rule in all_rules:
        if active_ids is None:
            result[rule.id] = True
        else:
            result[rule.id] = rule.id in active_ids
    return JSONResponse(result)


@router.post("/{rule_id}/toggle", summary="Toggle a rule's applied status")
async def toggle_rule(rule_id: str, request: Request) -> JSONResponse:
    """Toggle the applied/not-applied status of a single rule by ID."""
    from src.rules.loader import load_rules
    all_rules = load_rules(RULES_DIR)
    all_ids = {r.id for r in all_rules}
    if rule_id not in all_ids:
        raise HTTPException(status_code=404, detail=f"Rule ID '{rule_id}' not found.")

    active_ids = _load_active_ids()
    if active_ids is None:
        # First toggle — initialise from all IDs then flip the target
        active_ids = set(all_ids)

    if rule_id in active_ids:
        active_ids.discard(rule_id)
        applied = False
    else:
        active_ids.add(rule_id)
        applied = True

    _save_active_ids(active_ids)

    # Reload governance engine with updated active rules
    from src.engine.governance import GovernanceEngine
    all_loaded = all_rules  # already loaded above
    active_rules = [r for r in all_loaded if r.id in active_ids]
    data_provider = getattr(request.app.state.governance, "_data_provider", None)
    request.app.state.rules = active_rules
    request.app.state.governance = GovernanceEngine(
        rules=active_rules, data_provider=data_provider
    )

    return JSONResponse({"rule_id": rule_id, "applied": applied, "active_count": len(active_ids)})


@router.get("/{filename}", summary="Fetch a single rule file as JSON")
async def get_rule(filename: str) -> JSONResponse:
    """Parse and return a YAML rule file as a JSON object."""
    path = _resolve(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{filename} not found")
    data = yaml.safe_load(path.read_text())
    return JSONResponse(data)


@router.put("/{filename}", summary="Create or overwrite a rule file")
async def save_rule(filename: str, body: RuleSaveRequest) -> JSONResponse:
    """Serialise body.content back to YAML and write to disk.

    The filename in the URL must match body.filename.
    """
    if filename != body.filename:
        raise HTTPException(status_code=400, detail="URL filename and body filename must match.")
    path = _resolve(filename)
    RULES_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(body.content, allow_unicode=True, sort_keys=False, default_flow_style=False))
    return JSONResponse({"ok": True, "filename": filename})
