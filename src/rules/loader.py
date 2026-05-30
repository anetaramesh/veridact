from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .models import RuleDefinition

logger = logging.getLogger(__name__)


def load_rules(rules_dir: str | Path) -> list[RuleDefinition]:
    """Load all YAML rule packs from *rules_dir* and return validated rule objects.

    Each ``.yaml`` file may contain either a single rule dict or a top-level
    list of rule dicts.  Files are processed in alphabetical order so rule
    evaluation order is deterministic.

    Args:
        rules_dir: Path to the directory containing ``*.yaml`` rule pack files.

    Returns:
        Ordered list of validated :class:`~src.rules.models.RuleDefinition` objects.

    Raises:
        FileNotFoundError: If *rules_dir* does not exist.
        pydantic.ValidationError: If a YAML file contains an invalid rule schema.
    """
    rules_path = Path(rules_dir)
    rules: list[RuleDefinition] = []

    for yaml_file in sorted(rules_path.glob("*.yaml")):
        with yaml_file.open() as f:
            data = yaml.safe_load(f)

        # Support a file with a top-level list or a single rule dict
        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            rule = RuleDefinition.model_validate(entry)
            rules.append(rule)
            logger.debug("Loaded rule %s from %s", rule.id, yaml_file.name)

    logger.info("Loaded %d rules from %s", len(rules), rules_path)
    return rules
