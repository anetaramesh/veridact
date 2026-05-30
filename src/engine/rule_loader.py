from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .models import PolicyRule

logger = logging.getLogger(__name__)


def load_policy_rules(rules_dir: str | Path) -> list[PolicyRule]:
    """Load and validate YAML rule packs from *rules_dir* into :class:`PolicyRule` objects.

    Each ``.yaml`` file may contain either a single rule dict or a top-level
    list of rule dicts.  Files are processed in alphabetical order so rule
    evaluation order is deterministic.

    Only files that contain all required ``PolicyRule`` fields are loaded;
    legacy YAML files missing ``regulation_ref``, ``action_types``, ``severity``,
    or ``rationale_template`` will raise a ``pydantic.ValidationError``.

    Args:
        rules_dir: Path to the directory containing ``*.yaml`` rule pack files.

    Returns:
        Ordered list of validated :class:`~src.engine.models.PolicyRule` objects.

    Raises:
        FileNotFoundError: If *rules_dir* does not exist.
        pydantic.ValidationError: If a YAML file contains an invalid rule schema.
    """
    rules_path = Path(rules_dir)
    if not rules_path.exists():
        raise FileNotFoundError(f"Rules directory not found: {rules_path}")

    rules: list[PolicyRule] = []

    for yaml_file in sorted(rules_path.glob("*.yaml")):
        # Skip template files
        if yaml_file.stem.upper() == "TEMPLATE":
            continue

        with yaml_file.open() as f:
            data = yaml.safe_load(f)

        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            rule = PolicyRule.model_validate(entry)
            rules.append(rule)
            logger.debug("Loaded policy rule %s from %s", rule.id, yaml_file.name)

    logger.info("Loaded %d policy rules from %s", len(rules), rules_path)
    return rules
