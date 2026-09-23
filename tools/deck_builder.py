#!/usr/bin/env python3
"""Deterministic HTML deck builder for research runs.

``research_deck action='analytics'`` computes the numbers; this module renders
them into a professional, self-contained HTML5 report deck with inline SVG
charts and **no external resources**. Nothing is fetched from a CDN, so the
deck renders immediately in any browser, works offline, reopens from a
downloaded copy and prints to PDF without a blank first paint.

This exists because leaving the markup to the agent produced thin, inconsistent
decks (a grey header, prose sections, an unused Chart.js include that blocked
rendering). The owner requires a professional deck with analytics, charts,
tables, facts and citations — produced deterministically from the record, not
improvised.
"""
from __future__ import annotations

import html as _html
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence

# ── Palette ───────────────────────────────────────────────────────────
# Dark-first token design; the bare :root carries the light palette and a
# prefers-color-scheme block redefines the same tokens for dark. Everything
# renders through CSS custom properties so a single override flips the theme.
ACCENT = "#4f46e5"
ACCENT_DARK = "#3730a3"

_CONFIDENCE_COLORS = {
    "high": "#10b981",
    "medium": "#f59e0b",
    "low": "#ef4444",
}

# Chart series palette (accessible, distinct, dark/light safe).
_SERIES = ["#4f46e5", "#10b981", "#f59e0b", "#ef4444", "#06b6d4", "#8b5cf6",
           "#ec4899", "#84cc16", "#f97316", "#14b8a6"]


def _e(value: Any) -> str:
    """HTML-escape any dynamic value before it goes into markup."""
    return _html.escape(str(value if value is not None else ""))


def _slug(text: str, max_words: int = 6) -> str:
    """A safe filename slug from a question (letters, digits, dash)."""
    words = [w for w in (text or "").split() if any(c.isalnum() for c in w)]
    keep = words[:max_words]
    joined = "-".join(keep) if keep else "research"
    out = "".join(c.lower() if c.isalnum() else "-" for c in joined)
    out = "-".join(p for p in out.split("-") if p)
    return out[:80] or "research"


def _percent(share: Any) -> int:
    try:
        return int(round(float(share) * 100))
    except (TypeError, ValueError):
        return 0


# ── Chart renderers (inline SVG / CSS, no external libs) ──────────────

def _doughnut_svg(confidence_mix: Dict[str, Any], total: int) -> str:
    """Doughnut of high/medium/low claim shares. Centre shows the total."""
    size = 220
    cx = cy = size / 2
    radius = 78
    stroke = 26
    circumference = 2 * math.pi * radius

    order = ("high", "medium", "low")
    values = [(lvl, int(confidence_mix.get(lvl, {}).get("count", 0))) for lvl in order]
    segments = []
    offset = 0.0
    for lvl, count in values:
        if total <= 0 or count <= 0:
            continue
        frac = count / total
        seg_len = frac * circumference
        segments.append({
            "level": lvl,
            "color": _CONFIDENCE_COLORS[lvl],
            "dash": f"{seg_len:.2f} {circumference - seg_len:.2f}",
            "offset": -offset,
            "count": count,
            "pct": _percent(frac),
        })
        offset += seg_len

    rings = "\n".join(
        f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" '
        f'stroke="{s["color"]}" stroke-width="{stroke}" '
        f'stroke-dasharray="{s["dash"]}" stroke-dashoffset="{s["offset"]}" '
        f'transform="rotate(-90 {cx} {cy})" stroke-linecap="butt"/>'
        for s in segments
    )
    center = (
        f'<text x="{cx}" y="{cy - 6}" text-anchor="middle" class="donut-total">{total}</text>'
        f'<text x="{cx}" y="{cy + 14}" text-anchor="middle" class="donut-cap">claims</text>'
    )
    legend = "\n".join(
        f'<div class="legend-row"><span class="swatch" style="background:{s["color"]}"></span>'
        f'<span class="legend-label">{s["level"]}</span>'
        f'<span class="legend-val">{s["count"]} · {s["pct"]}%</span></div>'
        for s in segments
    )
    return (
        f'<svg viewBox="0 0 {size} {size}" class="donut" role="img" '
        f'aria-label="confidence distribution">{rings}{center}</svg>'
        f'<div class="legend">{legend}</div>'
    )


def _hbar_rows(items: Sequence[Dict[str, Any]], label_key: str, value_key: str,
               max_value: float) -> str:
    if not items:
        return '<p class="muted">No data recorded.</p>'
    rows = []
    for it in items:
        label = it.get(label_key, "")
        value = float(it.get(value_key, 0) or 0)
        width = (value / max_value * 100) if max_value > 0 else 0
        rows.append(
            f'<div class="hbar-row">'
            f'<span class="hbar-label">{_e(label)}</span>'
            f'<span class="hbar-track"><span class="hbar-fill" style="width:{width:.1f}%"></span></span>'
            f'<span class="hbar-val">{value:g}</span></div>'
        )
    return "\n".join(rows)


def _line_svg(points: Sequence[Dict[str, Any]], x_key: str, y_key: str,
              color: str = ACCENT) -> str:
    if not points:
        return '<p class="muted">No per-round data recorded.</p>'
    w, h = 480, 220
    pad_l, pad_r, pad_t, pad_b = 40, 16, 20, 32
    xs = [p.get(x_key) for p in points]
    ys = [float(p.get(y_key, 0) or 0) for p in points]
    x_min, x_max = (min(xs), max(xs)) if xs else (0, 1)
    y_max = max(ys) or 1
    if x_max == x_min:
        x_max = x_min + 1
    inner_w = w - pad_l - pad_r
    inner_h = h - pad_t - pad_b

    def px(x: Any) -> float:
        return pad_l + (x - x_min) / (x_max - x_min) * inner_w

    def py(y: float) -> float:
        return pad_t + inner_h - (y / y_max) * inner_h

    coords = [(px(x), py(y)) for x, y in zip(xs, ys)]
    polyline = " ".join(f"{cx:.1f},{cy:.1f}" for cx, cy in coords)
    dots = "\n".join(
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.5" fill="{color}"/>'
        for cx, cy in coords
    )
    grid = ""
    for g in range(0, int(y_max) + 1):
        if y_max > 0 and g <= y_max:
            gy = py(g)
            grid += (
                f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{w - pad_r}" y2="{gy:.1f}" '
                f'class="gridline"/>'
                f'<text x="{pad_l - 6}" y="{gy + 4:.1f}" text-anchor="end" class="axis">{g:g}</text>'
            )
    return (
        f'<svg viewBox="0 0 {w} {h}" class="linechart" role="img" aria-label="per-round progression">'
        f'{grid}'
        f'<polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="2.5" '
        f'stroke-linejoin="round" stroke-linecap="round"/>{dots}'
        f'</svg>'
    )


# ── Page assembly ─────────────────────────────────────────────────────

def build_deck_html(
    analytics: Dict[str, Any],
    limitations: Sequence[str],
    question: str,
    mode: str,
    persona: str,
    run_id: str,
) -> str:
    """Render a professional, self-contained HTML research deck."""
    totals = analytics.get("totals", {})
    conf_mix = analytics.get("confidence_mix", {})
    source_dist = analytics.get("source_distribution", [])
    coverage = analytics.get("coverage", [])
    claims_by_round = analytics.get("claims_by_round", [])
    claims_by_sub = analytics.get("claims_by_sub_question", {})
    citation_index = analytics.get("citation_index", [])
    contested = analytics.get("contested", [])
    resolutions = analytics.get("resolutions", [])
    candidates_ranked = analytics.get("candidates_ranked", [])
    open_gaps = analytics.get("open_gaps", [])

    total_claims = int(totals.get("claims", 0) or 0)
    unique_sources = int(totals.get("unique_sources", 0) or 0)
    distinct_origins = int(totals.get("distinct_origins", 0) or 0)
    rounds = int(totals.get("rounds", 0) or 0)
    contested_n = int(totals.get("contested", 0) or 0)

    high_count = int(conf_mix.get("high", {}).get("count", 0) or 0)
    conf_ratio = _percent(high_count / total_claims) if total_claims else 0

    covered = [c for c in coverage if not c.get("uncovered")]
    coverage_pct = _percent(len(covered) / len(coverage)) if coverage else 100

    now = datetime.now(timezone.utc).strftime("%B %d, %Y")

    # KPI cards.
    kpis = [
        ("Claims", total_claims, "verified, sourced findings"),
        ("Sources", unique_sources, f"across {distinct_origins} origins"),
        ("High confidence", f"{conf_ratio}%", f"{high_count} of {total_claims} claims"),
        ("Coverage", f"{coverage_pct}%", f"{len(covered)}/{len(coverage)} sub-questions"),
    ]

    # Findings by sub-question.
    findings_blocks = []
    for sq, claims in claims_by_sub.items():
        claim_rows = []
        for c in claims:
            conf = (c.get("confidence") or "medium").lower()
            color = _CONFIDENCE_COLORS.get(conf, _CONFIDENCE_COLORS["medium"])
            src_num = c.get("source_num") or 0
            cite = f'<span class="cite">[{src_num}]</span>' if src_num else ""
            basis = c.get("basis") or ""
            basis_block = '<div class="claim-basis">' + _e(basis) + '</div>' if basis else ''
            claim_rows.append(
                f'<div class="claim"><div class="claim-head">'
                f'<span class="badge" style="background:{color}1a;color:{color};border-color:{color}55">{_e(conf)}</span>'
                f'{cite}</div>'
                f'<div class="claim-text">{_e(c.get("claim"))}</div>'
                f'{basis_block}'
                f'</div>'
            )
        findings_blocks.append(
            f'<section><h2>{_e(sq)}</h2>{"".join(claim_rows)}</section>'
        )

    # Contested & resolutions.
    contested_rows = []
    for c in contested:
        state = "Resolved" if c.get("resolved") else "Open"
        color = _CONFIDENCE_COLORS["high"] if c.get("resolved") else _CONFIDENCE_COLORS["low"]
        contested_rows.append(
            f'<div class="claim"><span class="badge" style="background:{color}1a;color:{color};border-color:{color}55">{state}</span>'
            f'<div class="claim-text">{_e(c.get("claim"))}</div></div>'
        )
    resolutions_text = "".join(
        f'<p class="claim-text">• {_e(r.get("claim") if isinstance(r, dict) else r)}</p>'
        for r in resolutions
    )

    # Candidates (discovery / ranking).
    candidates_block = ""
    if candidates_ranked:
        cand_rows = "\n".join(
            f'<tr><td class="num">{i + 1}</td><td>{_e(c.get("name"))}</td>'
            f'<td class="num">{float(c.get("score") or 0):.2f}</td>'
            f'<td>{_e(c.get("evaluation") or c.get("rationale") or "")}</td></tr>'
            for i, c in enumerate(candidates_ranked)
        )
        candidates_block = (
            '<section><h2>Ranked Candidates</h2>'
            f'<div class="tablewrap"><table><thead><tr>'
            f'<th>#</th><th>Candidate</th><th>Score</th><th>Rationale</th></tr></thead>'
            f'<tbody>{cand_rows}</tbody></table></div></section>'
        )

    # Limitations.
    lim_items = limitations or open_gaps or ["No limitations recorded."]
    limitations_block = "\n".join(f"<li>{_e(l)}</li>" for l in lim_items)

    # References.
    ref_rows = "\n".join(
        f'<li><span class="cite">[{c.get("num")}]</span> {_e(c.get("source"))} '
        f'<span class="muted">({_e(c.get("origin"))})</span></li>'
        for c in citation_index
    ) or '<li class="muted">No sources recorded.</li>'

    # Charts.
    max_source = max((s.get("claims", 0) for s in source_dist), default=0)
    max_coverage = max((c.get("claims", 0) for c in coverage), default=0)
    source_bars = _hbar_rows(source_dist, "source", "claims", max_source)
    coverage_rows = []
    for c in coverage:
        sq = c.get("sub_question", "")
        n = int(c.get("claims", 0) or 0)
        high = int(c.get("high_confidence", 0) or 0)
        coverage_rows.append(
            f'<div class="hbar-row"><span class="hbar-label">{_e(sq)}</span>'
            f'<span class="hbar-track"><span class="hbar-fill" style="width:{_percent(n / max_coverage) if max_coverage else 0}%"></span>'
            f'<span class="hbar-fill hbar-high" style="width:{_percent(high / max_coverage) if max_coverage else 0}%"></span></span>'
            f'<span class="hbar-val">{n}</span></div>'
        )

    doughnut = _doughnut_svg(conf_mix, total_claims)
    line = _line_svg(claims_by_round, "round", "claims")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_e(question[:80])}</title>
<style>
:root{{
  --bg:#f6f7fb; --card:#ffffff; --ink:#0f172a; --muted:#64748b;
  --line:#e2e8f0; --accent:{ACCENT}; --accent-ink:#ffffff;
}}
@media (prefers-color-scheme: dark){{
  :root{{ --bg:#0b1120; --card:#111a2e; --ink:#e2e8f0; --muted:#94a3b8; --line:#1e293b; }}
}}
*{{ box-sizing:border-box; }}
body{{
  margin:0; padding:24px; background:var(--bg); color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  line-height:1.6; font-size:15px;
}}
.wrap{{ max-width:960px; margin:0 auto; }}
header.hero{{
  background:linear-gradient(135deg,{ACCENT} 0%,{ACCENT_DARK} 100%);
  color:#fff; border-radius:16px; padding:32px 36px; margin-bottom:24px;
}}
header.hero h1{{ margin:0 0 10px; font-size:1.7rem; line-height:1.25; }}
header.hero .meta{{ display:flex; gap:14px; flex-wrap:wrap; font-size:0.82rem; opacity:0.92; }}
header.hero .meta span{{ background:rgba(255,255,255,0.16); padding:4px 12px; border-radius:999px; }}
.kpis{{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:14px; margin-bottom:24px; }}
.kpi{{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:18px 20px; }}
.kpi .value{{ font-size:1.9rem; font-weight:700; color:var(--accent); font-variant-numeric:tabular-nums; }}
.kpi .label{{ font-weight:600; }}
.kpi .sub{{ color:var(--muted); font-size:0.8rem; }}
section{{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:22px 24px; margin-bottom:18px; }}
section h2{{ margin:0 0 14px; font-size:1.15rem; border-left:4px solid var(--accent); padding-left:12px; }}
.charts{{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:20px; }}
.chart-card{{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:20px; }}
.chart-card h3{{ margin:0 0 12px; font-size:0.95rem; color:var(--muted); font-weight:600; }}
.donut{{ width:100%; max-width:220px; display:block; margin:0 auto; }}
.donut-total{{ font-size:2rem; font-weight:700; fill:var(--ink); font-variant-numeric:tabular-nums; }}
.donut-cap{{ font-size:0.7rem; fill:var(--muted); }}
.legend{{ margin-top:12px; display:flex; flex-direction:column; gap:6px; }}
.legend-row{{ display:flex; align-items:center; gap:8px; font-size:0.85rem; }}
.swatch{{ width:10px; height:10px; border-radius:3px; display:inline-block; }}
.legend-label{{ text-transform:capitalize; flex:1; }}
.legend-val{{ color:var(--muted); font-variant-numeric:tabular-nums; }}
.hbar-row{{ display:flex; align-items:center; gap:10px; margin-bottom:10px; font-size:0.85rem; }}
.hbar-label{{ width:42%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; text-align:right; color:var(--muted); }}
.hbar-track{{ flex:1; height:16px; background:var(--line); border-radius:8px; overflow:hidden; display:flex; }}
.hbar-fill{{ height:100%; background:var(--accent); border-radius:8px; }}
.hbar-high{{ background:#10b981; }}
.hbar-val{{ width:34px; font-variant-numeric:tabular-nums; color:var(--muted); }}
.linechart{{ width:100%; height:auto; }}
.gridline{{ stroke:var(--line); stroke-width:1; }}
.axis{{ font-size:0.65rem; fill:var(--muted); }}
.claim{{ border-left:3px solid var(--line); padding:10px 14px; margin-bottom:12px; }}
.claim-head{{ display:flex; align-items:center; gap:8px; margin-bottom:4px; }}
.claim-text{{ font-size:0.95rem; }}
.claim-basis{{ color:var(--muted); font-size:0.8rem; margin-top:4px; }}
.badge{{ font-size:0.68rem; font-weight:700; padding:2px 10px; border-radius:999px; border:1px solid; text-transform:capitalize; }}
.cite{{ font-weight:700; color:var(--accent); font-size:0.78rem; }}
.muted{{ color:var(--muted); }}
.tablewrap{{ overflow-x:auto; }}
table{{ border-collapse:collapse; width:100%; font-size:0.85rem; }}
th,td{{ text-align:left; padding:8px 12px; border-bottom:1px solid var(--line); }}
th{{ color:var(--muted); font-weight:600; }}
td.num, th.num{{ text-align:right; font-variant-numeric:tabular-nums; }}
ol.refs{{ padding-left:20px; }}
ol.refs li{{ margin-bottom:6px; font-size:0.85rem; word-break:break-all; }}
ul.lim{{ padding-left:20px; }}
ul.lim li{{ margin-bottom:6px; }}
footer{{ text-align:center; color:var(--muted); font-size:0.8rem; padding:18px 0 6px; }}
@media print{{
  body{{ background:#fff; padding:0; }}
  section, .kpi, .chart-card{{ box-shadow:none; break-inside:avoid; }}
}}
</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <h1>{_e(question)}</h1>
    <div class="meta">
      <span>Mode: {_e(mode)}</span>
      <span>Persona: {_e(persona)}</span>
      <span>{_e(now)}</span>
      <span>Run: {_e(run_id)}</span>
    </div>
  </header>

  <div class="kpis">
    {''.join(f'<div class="kpi"><div class="value">{v}</div><div class="label">{k}</div><div class="sub">{s}</div></div>' for k, v, s in kpis)}
  </div>

  <section>
    <h2>Evidence Overview</h2>
    <div class="charts">
      <div class="chart-card"><h3>Confidence Distribution</h3>{doughnut}</div>
      <div class="chart-card"><h3>Claims by Source</h3>{source_bars}</div>
      <div class="chart-card"><h3>Coverage per Sub-Question</h3>{coverage_rows}</div>
      <div class="chart-card"><h3>Evidence Accumulation by Round</h3>{line}</div>
    </div>
  </section>

  {''.join(findings_blocks)}

  {'<section><h2>Contested Claims &amp; Resolutions</h2>' + ''.join(contested_rows) + resolutions_text + '</section>' if (contested_rows or resolutions_text) else ''}

  {candidates_block}

  <section>
    <h2>Limitations</h2>
    <ul class="lim">{limitations_block}</ul>
  </section>

  <section>
    <h2>References</h2>
    <ol class="refs">{ref_rows}</ol>
  </section>

  <footer>Prepared by Elidia Agent · {_e(now)}</footer>
</div>
</body>
</html>
"""
