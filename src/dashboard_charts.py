"""Hand-built SVG and HTML charts for the results dashboard (src/dashboard.py).

Theme-dependent colours come from CSS classes (see dashboard_assets/dashboard.css);
only the fixed status colours are written inline. Every mark carries a <title>
tooltip with its exact value.
"""
from __future__ import annotations

import html
import math

import numpy as np
import pandas as pd

from src.transect_map import STATUS
from src.vegetation import parse_point

ICON = {**{k: v["icon"] for k, v in STATUS.items()}, "info": "i"}
COLOUR = {**{k: v["color"] for k, v in STATUS.items()}, "info": "#8a8983"}
SEVERITY_STATUS = {"error": "critical", "warning": "warning", "info": "info"}
PRIORITY_ORDER = ["critical", "serious", "warning", "good"]

# Short display names for QA rules; anything missing falls back to the catalogue message.
RULE_LABELS = {
    "Q04": "Quadrat off the registered line", "SP01": "Name has extra spaces", "S05": "Device clock offset not EAT",
    "P02": "Transect not north–south", "SP05": "Stored count ≠ recomputed", "P01": "Transect length out of range",
    "S01": "Duplicate submission for plot", "SP02": "Free-text name near a listed name",
    "SP03": "Possible genus misspelling", "S02": "Submission rejected in ODK", "P03": "Midpoint far from planned",
    "SP00": "Species entry has no name",
}


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def short_plot(plot_name: str) -> str:
    return plot_name.rsplit("_", 1)[-1]


def ic(status: str, icon: str | None = None) -> str:
    """Status disc: colour plus icon, never colour alone."""
    return f'<i class="ic s-{status}" aria-hidden="true">{icon or ICON[status]}</i>'


def swatch(colour: str) -> str:
    return f'<span class="sv" style="background:{colour}"></span>'


# ---------------------------------------------------------------------------- plot map
def _label_offset(x: float, y: float, others: list[tuple[float, float]], width: int, height: int,
                  label_w: float = 44) -> tuple[float, float]:
    """Pick the label position (text baseline start) farthest from neighbouring points."""
    def clearance(lx: float, ly: float) -> float:
        if lx < 2 or lx + label_w > width - 2 or ly - 10 < 2 or ly > height - 2:
            return -1
        return min((math.hypot(max(lx - px, 0, px - lx - label_w), max(ly - 10 - py, 0, py - ly))
                    for px, py in others), default=99)
    candidates = [(x + 9, y - 8), (x + 9, y + 16), (x - 9 - label_w, y - 8), (x - 9 - label_w, y + 16),
                  (x + 12, y - 22), (x + 12, y + 30), (x - 12 - label_w, y - 22), (x - 12 - label_w, y + 30)]
    return max(candidates, key=lambda c: clearance(*c))


def plot_map_svg(queue: pd.DataFrame, coverage: pd.DataFrame, centroids: pd.DataFrame | None,
                 width: int = 760, height: int = 300, pad: int = 26) -> str:
    """Registered plots coloured by review priority; unsurveyed planned locations drawn separately."""
    q = queue.dropna(subset=["m_lat", "m_lon"])
    planned = pd.DataFrame(columns=["plot_name", "lat", "lon", "sample_status", "is_viable"])
    if centroids is not None:
        xy = centroids["geometry"].apply(parse_point)
        planned = (pd.DataFrame({"plot_name": centroids["choice_name"], "lat": xy.str[0], "lon": xy.str[1]})
                   .merge(coverage[["plot_name", "sample_status", "is_viable"]], on="plot_name", how="left"))
        planned = planned[~planned.plot_name.isin(q.plot_name)].dropna(subset=["lat"])
    lat, lon = pd.concat([q.m_lat, planned.lat]), pd.concat([q.m_lon, planned.lon])
    kx = math.cos(math.radians(lat.mean()))  # equal-distance scaling near the equator
    scale = min((width - 2 * pad) / ((lon.max() - lon.min()) * kx), (height - 2 * pad) / (lat.max() - lat.min()))
    x0 = pad + (width - 2 * pad - (lon.max() - lon.min()) * kx * scale) / 2
    X = lambda lo: x0 + (lo - lon.min()) * kx * scale
    Y = lambda la: height - pad - (la - lat.min()) * scale
    points = [(X(a), Y(b)) for a, b in zip(lon, lat)]
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
           f'aria-label="Map of {len(q)} registered plots coloured by spatial review priority">']
    for p in planned.itertuples():
        x, y, name = X(p.lon), Y(p.lat), short_plot(p.plot_name)
        if p.is_viable == "no":
            out.append(f'<g><title>Plot {name}: registered non-viable</title><text x="{x:.1f}" y="{y + 5:.1f}" '
                       f'text-anchor="middle" class="xx" fill="{COLOUR["critical"]}">✕</text>'
                       f'<text x="{x + 9:.1f}" y="{y + 4:.1f}" class="lb">{name}</text></g>')
        elif p.sample_status == "primary":
            out.append(f'<g><title>Plot {name}: primary, not registered</title><circle cx="{x:.1f}" cy="{y:.1f}" r="6" '
                       f'class="planned"/><text x="{x + 9:.1f}" y="{y + 4:.1f}" class="lb">{name}</text></g>')
        else:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" class="backup"><title>Plot {name}: backup, unused</title></circle>')
    labels = []
    for r in q.sort_values("rank", ascending=False).itertuples():
        x, y, crit = X(r.m_lon), Y(r.m_lat), r.priority == "critical"
        off = "" if pd.isna(r.flagged_quadrats) else f" · {int(r.flagged_quadrats)}/{int(r.actual_quadrats)} quadrats off the line"
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{7 if crit else 5.5}" fill="{COLOUR[r.priority]}" class="halo">'
                   f'<title>Plot {short_plot(r.plot_name)}: {STATUS[r.priority]["label"]}{off}</title></circle>')
        if crit:
            lx, ly = _label_offset(x, y, [p for p in points if math.hypot(p[0] - x, p[1] - y) > 1], width, height)
            near_x = min(max(x, lx), lx + 44)
            labels.append(f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{near_x:.1f}" y2="{ly - 4:.1f}" class="leader"/>'
                          f'<text x="{lx:.1f}" y="{ly:.1f}" class="lb lbk">Plot {short_plot(r.plot_name)}</text>')
    return "".join(out + labels) + "</svg>"


def map_legend(counts: dict, n_unregistered: int, n_nonviable: int) -> str:
    items = [f'<span class="lg">{ic(k)}{STATUS[k]["label"]} <b>{counts.get(k, 0)}</b></span>' for k in PRIORITY_ORDER]
    items.append(f'<span class="lg"><span class="ring"></span>Primary, not registered <b>{n_unregistered}</b></span>')
    items.append(f'<span class="lg"><span class="xx">✕</span>Non-viable <b>{n_nonviable}</b></span>')
    return '<div class="legend">' + "".join(items) + "</div>"


# ---------------------------------------------------------------------------- birds
def calibration_svg(s: dict, val: pd.DataFrame | None, target: float) -> str:
    """Expert checks, fitted P(correct), target line and GLM / Firth cutoffs for one species."""
    W, H, left, right, top, bottom = 300, 180, 34, 10, 10, 30
    xs = lambda c: left + c * (W - left - right)
    ys = lambda p: top + (1 - p) * (H - top - bottom)
    t = s["t"]
    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="{esc(s["name"])}: expert checks against '
           f'BirdNET score, with the fitted probability of a correct call">']
    for p in (0, 0.5, 1):
        out.append(f'<line x1="{left}" x2="{W - right}" y1="{ys(p):.1f}" y2="{ys(p):.1f}" class="gr"/>'
                   f'<text x="{left - 5}" y="{ys(p) + 4:.1f}" class="ax" text-anchor="end">{p:.0%}</text>')
    for c in (0, 0.5, 1):
        out.append(f'<text x="{xs(c):.1f}" y="{H - 14}" class="ax" text-anchor="middle">{c:g}</text>')
    out.append(f'<text x="{(left + W - right) / 2:.0f}" y="{H - 1}" class="ax" text-anchor="middle">BirdNET score</text>')
    out.append(f'<line x1="{left}" x2="{W - right}" y1="{ys(target):.1f}" y2="{ys(target):.1f}" class="target">'
               f'<title>Target P(correct) = {target:g}</title></line>')
    if val is not None:
        rng = np.random.default_rng(7)  # fixed jitter so rebuilds are identical
        d = val[val.commonName == s["name"]]
        for c, o in zip(d.confidence, d.outcome):
            jitter = abs(rng.uniform(0, 0.035))
            out.append(f'<circle cx="{xs(c):.1f}" cy="{ys(1 - jitter if o == 1 else jitter):.1f}" r="2.6" '
                       f'class="{"pt-ok" if o == 1 else "pt-bad"}"><title>score {c:.3f} · {"correct" if o == 1 else "wrong"}</title></circle>')
    if pd.notna(t.b1):
        grid = np.linspace(0.101, 0.9995, 160)
        clipped = np.clip(grid, t.eps, 1 - t.eps)
        prob = 1 / (1 + np.exp(-(t.b0 + t.b1 * np.log(clipped / (1 - clipped)))))
        pts = " ".join(f"{xs(g):.1f},{ys(p):.1f}" for g, p in zip(grid, prob))
        out.append(f'<polyline points="{pts}" class="curve"><title>Fitted P(correct)</title></polyline>')
        if pd.notna(t.conf_threshold) and t.conf_threshold <= 1:
            out.append(f'<line x1="{xs(t.conf_threshold):.1f}" x2="{xs(t.conf_threshold):.1f}" y1="{top}" y2="{H - bottom}" '
                       f'stroke="{COLOUR[s["key"]]}" stroke-width="2"><title>GLM cutoff {t.conf_threshold:.3f}</title></line>')
        if pd.notna(s["firth"]):
            out.append(f'<line x1="{xs(s["firth"]):.1f}" x2="{xs(s["firth"]):.1f}" y1="{top}" y2="{H - bottom}" class="firth">'
                       f'<title>Firth cutoff {s["firth"]:.3f}</title></line>')
    else:
        msg = "No curve: every check was correct" if int(t.n_wrong) == 0 else "No curve fitted"
        out.append(f'<text x="{(left + W - right) / 2:.0f}" y="{ys(0.5) + 4:.1f}" class="lb" text-anchor="middle">{msg}</text>')
    return "".join(out) + "</svg>"


FUNNEL_KEY = (f'{swatch("var(--muted-bar)")}predictions {swatch(COLOUR["warning"])}fitted candidates '
              f'{swatch(COLOUR["good"])}released observations')


def funnel(species: list[dict]) -> str:
    """Predictions → fitted candidates → released observations, one bar per species."""
    top = max(s["preds"] for s in species) or 1
    rows = []
    for s in species:
        tip = f'{s["preds"]:,} predictions · {s["cands"]:,} fitted candidates · {s["obs"]:,} released observations'
        rows.append(f'<div class="fu"><div class="ful">{esc(s["name"])}</div><div class="fut" title="{tip}">'
                    f'<div class="fb pred" style="width:{s["preds"] / top * 100:.2f}%"></div>'
                    f'<div class="fb" style="width:{s["cands"] / top * 100:.2f}%;background:{COLOUR["warning"]}"></div>'
                    f'<div class="fb" style="width:{s["obs"] / top * 100:.2f}%;background:{COLOUR["good"]}"></div></div>'
                    f'<div class="fun">{s["obs"]:,}<small> of {s["preds"]:,}</small></div></div>')
    return "".join(rows)


# ---------------------------------------------------------------------------- vegetation
def effort_svg(effort: pd.DataFrame) -> str:
    """New taxa expected in the last five quadrats, one stem per plot, sorted high to low."""
    e = effort.sort_values("expected_new_taxa_in_final_up_to_5_quadrats", ascending=False).reset_index(drop=True)
    W, H, pad = 520, 210, 30
    top = max(1, math.ceil(e.expected_new_taxa_in_final_up_to_5_quadrats.max()))
    Y = lambda val: H - pad - val / top * (H - 2 * pad)
    step = (W - pad - 14) / max(len(e), 1)
    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Expected new taxa in the last five quadrats, '
           f'one stem per plot, sorted from most to least">']
    for val in range(0, top + 1, max(1, top // 3)):
        out.append(f'<line x1="{pad}" x2="{W - 6}" y1="{Y(val):.1f}" y2="{Y(val):.1f}" class="gr"/>'
                   f'<text x="{pad - 6}" y="{Y(val) + 4:.1f}" class="ax" text-anchor="end">{val}</text>')
    for i, r in e.iterrows():
        x, y = pad + 8 + i * step, Y(r.expected_new_taxa_in_final_up_to_5_quadrats)
        kind = "cont" if r.effort_interpretation.startswith("continued") else "flat"
        out.append(f'<g><title>Plot {short_plot(r.plot_name)}: +{r.expected_new_taxa_in_final_up_to_5_quadrats:.1f} taxa '
                   f'in the last 5 quadrats ({esc(r.effort_interpretation)})</title>'
                   f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{H - pad}" y2="{y:.1f}" class="stem-{kind}" stroke-width="2" opacity=".6"/>'
                   f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" class="dot-{kind} halo"/></g>')
        if i == 0:
            out.append(f'<text x="{x + 8:.1f}" y="{y + 4:.1f}" class="lb lbk">Plot {short_plot(r.plot_name)}</text>')
    out.append(f'<text x="{pad}" y="{H - 8}" class="ax">plots, sorted by new taxa added in the last 5 quadrats</text>')
    return "".join(out) + "</svg>"


def rule_bars(flags: pd.DataFrame, rules: pd.DataFrame) -> str:
    """Flag count per QA rule, coloured and iconed by severity."""
    counts = flags.groupby(["rule_id", "severity"]).size().rename("n").reset_index().sort_values("n", ascending=False)
    messages = rules.set_index("rule_id")["message"]
    top = counts.n.max()
    rows = []
    for r in counts.itertuples():
        key = SEVERITY_STATUS.get(r.severity, "info")
        full = messages.get(r.rule_id, r.rule_id)
        rows.append(f'<div class="br" title="{esc(r.severity)}: {esc(full)}"><div class="bl">{ic(key)}<code>{r.rule_id}</code>'
                    f'{esc(RULE_LABELS.get(r.rule_id, full))}</div><div class="bt"><div class="bf" '
                    f'style="width:{r.n / top * 100:.1f}%;background:{COLOUR[key]}"></div></div><div class="bn">{r.n}</div></div>')
    return "".join(rows)
