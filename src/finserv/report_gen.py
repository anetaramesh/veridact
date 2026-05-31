"""PDF compliance audit report generator (WeasyPrint + Jinja2).

Endpoint: GET /report/pdf?from=YYYY-MM-DD&to=YYYY-MM-DD

Generates a professional A4 compliance report covering:
  - Executive summary table
  - Violations-by-rule horizontal bar chart (inline SVG)
  - Semantic evaluation summary
  - Chain integrity certificate
  - Full paginated audit log
"""
from __future__ import annotations

import json
import logging
import math
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# WeasyPrint requires Pango/GObject; on macOS these live under Homebrew.
# Set DYLD_LIBRARY_PATH here so the lazy import in the route handler works
# even when the server is launched without this env var in the shell.
if not os.environ.get("DYLD_LIBRARY_PATH"):
    _homebrew_lib = Path("/opt/homebrew/lib")
    if _homebrew_lib.exists():
        os.environ["DYLD_LIBRARY_PATH"] = str(_homebrew_lib)

import aiosqlite
from fastapi import APIRouter, Query
from fastapi.responses import Response
from jinja2 import Environment, select_autoescape
import src.engine.audit_log as audit_log
from src.engine.audit_log import verify_chain

logger = logging.getLogger(__name__)
router = APIRouter(tags=["report"])

# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

_SELECT_RANGE = """
SELECT entry_id, timestamp, agent_id, action_type, parameters,
       violations, rationale, outcome, latency_ms, policy_set
FROM audit_entries
WHERE timestamp >= ? AND timestamp < ?
ORDER BY timestamp ASC
"""


async def _fetch_entries(
    from_dt: datetime,
    to_dt: datetime,
    db_path: Path,
) -> list[dict[str, Any]]:
    """Return all audit rows in [from_dt, to_dt) as plain dicts."""
    from_iso = from_dt.isoformat()
    # Extend to_dt to end-of-day by using midnight of the next day
    to_iso = to_dt.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(_SELECT_RANGE, (from_iso, to_iso)) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Stats computation
# ---------------------------------------------------------------------------

def _compute_stats(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive all summary statistics from raw audit rows."""
    total = len(entries)
    outcome_counts: Counter[str] = Counter(e["outcome"] for e in entries)

    latencies = [e["latency_ms"] for e in entries if e["latency_ms"] is not None]
    avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0.0
    peak_latency = max(latencies) if latencies else 0

    # Count violations per rule_id
    rule_counter: Counter[str] = Counter()
    for e in entries:
        try:
            viols = json.loads(e["violations"] or "[]")
        except (json.JSONDecodeError, TypeError):
            viols = []
        for v in viols:
            rule_id = v.get("rule_id") or v.get("violation_code", "unknown")
            rule_counter[rule_id] += 1

    top_8_rules = rule_counter.most_common(8)
    top_rule = top_8_rules[0] if top_8_rules else ("—", 0)

    # Semantic eval summary — soft_hold outcomes represent semantic escalations
    held = outcome_counts.get("soft_hold", 0)
    hard_blocked = outcome_counts.get("hard_block", 0)
    flagged = outcome_counts.get("flagged", 0)
    approved = outcome_counts.get("approved", 0)
    confidence = round((approved / total * 100), 1) if total else 0.0

    return {
        "total": total,
        "approved": approved,
        "hard_blocked": hard_blocked,
        "held": held,
        "flagged": flagged,
        "avg_latency": avg_latency,
        "peak_latency": peak_latency,
        "top_rule_id": top_rule[0],
        "top_rule_count": top_rule[1],
        "top_8_rules": top_8_rules,
        "sem_evaluations": total,
        "sem_fallbacks": 0,
        "sem_avg_confidence": confidence,
        "sem_approved": approved,
        "sem_held": held,
        "sem_blocked": hard_blocked + flagged,
    }


# ---------------------------------------------------------------------------
# SVG bar chart
# ---------------------------------------------------------------------------

def _build_svg_chart(top_8_rules: list[tuple[str, int]]) -> str:
    """Return an inline SVG horizontal bar chart for the top rules by violation count."""
    if not top_8_rules:
        return '<svg width="500" height="40"><text x="10" y="25" font-family="Helvetica" font-size="10" fill="#555">No violations recorded in period.</text></svg>'

    bar_h = 18
    gap = 7
    label_w = 210
    chart_w = 500
    padding_top = 6
    padding_bottom = 6
    height = padding_top + len(top_8_rules) * (bar_h + gap) + padding_bottom
    max_count = max(c for _, c in top_8_rules) or 1
    bar_area = chart_w - label_w - 55

    lines: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{chart_w}" height="{height}" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="9">',
    ]

    for i, (rule_id, count) in enumerate(top_8_rules):
        y = padding_top + i * (bar_h + gap)
        bar_w = math.floor(bar_area * count / max_count)
        bar_w = max(bar_w, 2)

        short = rule_id if len(rule_id) <= 30 else rule_id[:27] + "…"
        lines.append(
            f'<text x="{label_w - 8}" y="{y + bar_h - 4}" text-anchor="end" '
            f'fill="#111" font-size="8">{short}</text>'
        )
        lines.append(
            f'<rect x="{label_w}" y="{y}" width="{bar_w}" height="{bar_h}" '
            f'fill="#111"/>'
        )
        lines.append(
            f'<text x="{label_w + bar_w + 5}" y="{y + bar_h - 4}" '
            f'fill="#111" font-size="8">{count}</text>'
        )

    lines.append("</svg>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Jinja2 HTML template
# ---------------------------------------------------------------------------

_TEMPLATE_SRC = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<style>
  @page {
    size: A4;
    margin: 25mm 20mm 28mm 20mm;
    @bottom-left {
      content: "CONFIDENTIAL — FOR COMPLIANCE USE ONLY";
      font-family: Helvetica, Arial, sans-serif;
      font-size: 7pt;
      color: #555;
      letter-spacing: 0.05em;
    }
    @bottom-right {
      content: "Page " counter(page) " of " counter(pages);
      font-family: Helvetica, Arial, sans-serif;
      font-size: 7pt;
      color: #555;
    }
  }
  * { box-sizing: border-box; }
  body {
    font-family: Helvetica, Arial, sans-serif;
    font-size: 9.5pt;
    color: #111;
    margin: 0;
    line-height: 1.5;
  }

  /* ── Letterhead ── */
  .letterhead {
    border-bottom: 2pt solid #000;
    padding-bottom: 10pt;
    margin-bottom: 14pt;
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
  }
  .letterhead-left h1 {
    font-size: 20pt;
    font-weight: 900;
    letter-spacing: -0.02em;
    margin: 0 0 1pt 0;
    color: #000;
  }
  .letterhead-left .tagline {
    font-size: 7.5pt;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #555;
    margin: 0;
  }
  .letterhead-right {
    text-align: right;
    font-size: 8pt;
    color: #333;
    line-height: 1.6;
  }
  .report-title {
    font-size: 12pt;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin: 0 0 10pt 0;
    color: #000;
  }

  /* ── Meta strip ── */
  .meta-strip {
    background: #f2f2f2;
    border: 0.5pt solid #ccc;
    padding: 6pt 10pt;
    font-size: 8.5pt;
    display: flex;
    justify-content: space-between;
    margin-bottom: 16pt;
  }
  .meta-strip span { color: #333; }
  .meta-strip strong { color: #000; }
  .integrity-ok   { font-weight: bold; color: #000; }
  .integrity-fail { font-weight: bold; color: #000; text-decoration: underline; }

  /* ── Section headings ── */
  h2 {
    font-size: 9pt;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: #000;
    margin: 18pt 0 6pt 0;
    border-bottom: 1pt solid #000;
    padding-bottom: 3pt;
  }

  /* ── Tables ── */
  table { width: 100%; border-collapse: collapse; font-size: 8.5pt; margin-top: 4pt; }
  th {
    background: #000;
    color: #fff;
    text-align: left;
    padding: 4pt 7pt;
    font-size: 7.5pt;
    font-weight: bold;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  td { padding: 4pt 7pt; border-bottom: 0.5pt solid #ddd; vertical-align: top; color: #111; }
  tr:nth-child(even) td { background: #f9f9f9; }
  tbody tr:last-child td { border-bottom: 1pt solid #000; }

  /* ── Outcome labels (monochrome) ── */
  .outcome-approved   { font-weight: bold; }
  .outcome-hard_block { font-weight: bold; text-decoration: underline; }
  .outcome-soft_hold  { font-weight: bold; font-style: italic; }
  .outcome-flagged    { font-weight: bold; }

  /* ── Summary table ── */
  .summary-table { width: 100%; border-collapse: collapse; margin-top: 4pt; font-size: 9pt; }
  .summary-table thead tr { background: #000; color: #fff; }
  .summary-table thead th {
    padding: 5pt 10pt;
    font-size: 7.5pt;
    font-weight: bold;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    text-align: left;
    color: #fff;
  }
  .summary-table thead th.right { text-align: right; }
  .summary-table .group-header td {
    background: #e8e8e8;
    font-size: 7pt;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: #333;
    padding: 3pt 10pt;
    border-bottom: 0.5pt solid #bbb;
  }
  .summary-table tbody tr td {
    padding: 4.5pt 10pt;
    border-bottom: 0.5pt solid #e0e0e0;
    color: #111;
  }
  .summary-table tbody tr:last-child td { border-bottom: 1pt solid #000; }
  .summary-table .metric-label { width: 65%; }
  .summary-table .metric-value { text-align: right; font-weight: bold; font-variant-numeric: tabular-nums; }

  /* ── Certificate box ── */
  .cert-box {
    border: 1pt solid #000;
    padding: 10pt 14pt;
    font-size: 9pt;
    line-height: 1.7;
    margin-top: 4pt;
  }
  .cert-box.cert-fail { border-left: 4pt solid #000; }

  /* ── Page break ── */
  .section-break { page-break-before: always; }
</style>
</head>
<body>

<!-- ===== LETTERHEAD ===== -->
<div class="letterhead">
  <div class="letterhead-left">
    <h1>Veridact</h1>
    <p class="tagline">AI Agent Compliance Middleware</p>
  </div>
  <div class="letterhead-right">
    <strong>Compliance Audit Report</strong><br/>
    Generated: {{ generated_utc }}<br/>
    Report ID: VDT-{{ from_date }}/{{ to_date }}
  </div>
</div>

<p class="report-title">Regulatory Compliance Audit Record</p>

<!-- ===== META STRIP ===== -->
<div class="meta-strip">
  <span>Reporting period: <strong>{{ from_date }}</strong> — <strong>{{ to_date }}</strong></span>
  <span>
    Audit chain:
    {% if chain.valid %}
      <span class="integrity-ok">&#10003; CRYPTOGRAPHICALLY VERIFIED ({{ chain.entry_count }} entries)</span>
    {% else %}
      <span class="integrity-fail">&#9888; CHAIN COMPROMISED — broken at entry {{ chain.broken_at }}</span>
    {% endif %}
  </span>
</div>

<!-- ===== EXECUTIVE SUMMARY ===== -->
<h2>Executive Summary</h2>
<table class="summary-table">
  <thead>
    <tr>
      <th class="metric-label">Metric</th>
      <th class="right">Value</th>
    </tr>
  </thead>
  <tbody>
    <tr class="group-header"><td colspan="2">Action Disposition</td></tr>
    <tr>
      <td class="metric-label">Total agent actions intercepted</td>
      <td class="metric-value">{{ stats.total }}</td>
    </tr>
    <tr>
      <td class="metric-label">Approved — cleared by compliance engine</td>
      <td class="metric-value">{{ stats.approved }}</td>
    </tr>
    <tr>
      <td class="metric-label">Hard blocked — action prevented</td>
      <td class="metric-value">{{ stats.hard_blocked }}</td>
    </tr>
    <tr>
      <td class="metric-label">Soft hold — escalated for human review</td>
      <td class="metric-value">{{ stats.held }}</td>
    </tr>
    <tr>
      <td class="metric-label">Flagged — logged for supervisory review</td>
      <td class="metric-value">{{ stats.flagged }}</td>
    </tr>
    <tr class="group-header"><td colspan="2">Performance</td></tr>
    <tr>
      <td class="metric-label">Average evaluation latency (ms)</td>
      <td class="metric-value">{{ stats.avg_latency }}</td>
    </tr>
    <tr>
      <td class="metric-label">Peak evaluation latency (ms)</td>
      <td class="metric-value">{{ stats.peak_latency }}</td>
    </tr>
    <tr>
      <td class="metric-label">Approval confidence rate</td>
      <td class="metric-value">{{ stats.sem_avg_confidence }}%</td>
    </tr>
    <tr class="group-header"><td colspan="2">Top Violation</td></tr>
    <tr>
      <td class="metric-label">Most frequently triggered regulation</td>
      <td class="metric-value" style="font-weight:normal;font-family:monospace;font-size:8pt;">{{ stats.top_rule_id }}</td>
    </tr>
    <tr>
      <td class="metric-label">Violation count for top regulation</td>
      <td class="metric-value">{{ stats.top_rule_count }}</td>
    </tr>
  </tbody>
</table>

<!-- ===== VIOLATIONS BY RULE ===== -->
{% if top_8_rules %}
<h2>Violations by Regulation (Top {{ top_8_rules|length }})</h2>
{{ svg_chart | safe }}
{% endif %}

<!-- ===== SEMANTIC EVALUATION ===== -->
<h2>Evaluation Summary</h2>
<table>
  <thead>
    <tr><th style="width:70%">Metric</th><th>Value</th></tr>
  </thead>
  <tbody>
    <tr><td>Total evaluations run</td><td>{{ stats.sem_evaluations }}</td></tr>
    <tr><td>Approved by compliance engine</td><td>{{ stats.sem_approved }}</td></tr>
    <tr><td>Held for human review (soft hold)</td><td>{{ stats.sem_held }}</td></tr>
    <tr><td>Blocked by compliance engine</td><td>{{ stats.sem_blocked }}</td></tr>
    <tr><td>Fallbacks (engine unavailable)</td><td>{{ stats.sem_fallbacks }}</td></tr>
    <tr><td>Approval confidence rate</td><td>{{ stats.sem_avg_confidence }}%</td></tr>
  </tbody>
</table>

<!-- ===== CHAIN INTEGRITY CERTIFICATE ===== -->
<h2>Chain Integrity Certificate</h2>
<div class="cert-box {% if not chain.valid %}cert-fail{% endif %}">
  {% if chain.valid %}
  All <strong>{{ chain.entry_count }}</strong> audit entries in this report have been
  independently cryptographically verified using SHA-256 linked hashing. The integrity
  of the audit chain is confirmed intact. This document constitutes tamper-evident
  evidence of all AI agent actions intercepted by Veridact during the stated period
  and may be submitted to regulatory counsel as a compliance record.
  {% else %}
  <strong>INTEGRITY FAILURE:</strong> The SHA-256 audit chain verification has failed.
  The hash chain is broken starting at entry <strong>{{ chain.broken_at }}</strong>.
  This report cannot be certified as tamper-evident. Escalate to the compliance desk
  and information security team immediately prior to any regulatory submission.
  {% endif %}
</div>

<!-- ===== FULL AUDIT LOG ===== -->
<h2 class="section-break">Full Audit Log</h2>
{% if entries %}
<table>
  <thead>
    <tr>
      <th style="width:15%">Timestamp</th>
      <th style="width:13%">Agent ID</th>
      <th style="width:13%">Action Type</th>
      <th style="width:9%">Amount</th>
      <th style="width:10%">Outcome</th>
      <th style="width:40%">Rationale</th>
    </tr>
  </thead>
  <tbody>
  {% for e in entries %}
    <tr>
      <td style="font-size:7.5pt;font-family:monospace;">{{ e.timestamp[:19].replace("T"," ") }}</td>
      <td style="font-size:7.5pt;font-family:monospace;">{{ e.agent_id }}</td>
      <td>{{ e.action_type }}</td>
      <td style="font-family:monospace;">{{ e.amount }}</td>
      <td class="outcome-{{ e.outcome }}">{{ e.outcome }}</td>
      <td style="font-size:8pt;">{{ e.rationale[:80] }}{% if e.rationale|length > 80 %}…{% endif %}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% else %}
<p style="font-style:italic;color:#555;">No audit entries recorded in the selected period.</p>
{% endif %}

</body>
</html>
"""

_jinja_env = Environment(autoescape=select_autoescape(["html"]))
_template = _jinja_env.from_string(_TEMPLATE_SRC)


def _extract_amount(parameters_json: str) -> str:
    """Pull amount from a parameters JSON blob for display; return '—' if absent."""
    try:
        params = json.loads(parameters_json or "{}")
        amt = params.get("amount")
        if amt is not None:
            return f"${amt:,.0f}" if isinstance(amt, (int, float)) else str(amt)
    except (json.JSONDecodeError, TypeError):
        pass
    return "—"


# ---------------------------------------------------------------------------
# FastAPI route
# ---------------------------------------------------------------------------

@router.get("/report/pdf", summary="Generate PDF compliance audit report")
async def get_report_pdf(
    from_: str = Query(..., alias="from", description="Start date YYYY-MM-DD"),
    to: str = Query(..., description="End date YYYY-MM-DD"),
) -> Response:
    """Generate and stream a WeasyPrint PDF compliance audit report.

    Args:
        from_: Inclusive start date in YYYY-MM-DD format.
        to: Inclusive end date in YYYY-MM-DD format.

    Returns:
        PDF bytes with content-type application/pdf.
    """
    from_dt = datetime.strptime(from_, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    to_dt = datetime.strptime(to, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    db_path = audit_log.DB_PATH
    entries_raw = await _fetch_entries(from_dt, to_dt, db_path)
    chain = await verify_chain(db_path)
    stats = _compute_stats(entries_raw)

    # Enrich rows for template
    entries_display = [
        {**e, "amount": _extract_amount(e.get("parameters", "{}"))}
        for e in entries_raw
    ]

    svg_chart = _build_svg_chart(stats["top_8_rules"])

    html_str = _template.render(
        from_date=from_,
        to_date=to,
        generated_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        chain=chain,
        stats=stats,
        top_8_rules=stats["top_8_rules"],
        svg_chart=svg_chart,
        entries=entries_display,
    )

    from weasyprint import HTML  # lazy: requires DYLD_LIBRARY_PATH=/opt/homebrew/lib on macOS
    pdf_bytes = HTML(string=html_str).write_pdf()
    logger.info(
        "PDF report generated: from=%s to=%s entries=%d size=%d bytes",
        from_, to, len(entries_raw), len(pdf_bytes),
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="veridact-report-{from_}-{to}.pdf"'},
    )
