"""Interactive review map for herbaceous transects.

Builds a Folium map from the tables produced in notebook 02. It never edits or
corrects coordinates: every position is drawn exactly as recorded, and colour
encodes the spatial review priority derived from existing QA flags.
"""
from __future__ import annotations

import html
import json

import numpy as np
import pandas as pd
import folium
from folium.plugins import Fullscreen, MiniMap
from branca.element import Element, MacroElement
from jinja2 import Template

from src.vegetation import parse_point

# Status palette (fixed roles). Colour is always paired with an icon and a label.
STATUS = {
    "critical": {"color": "#d03b3b", "icon": "▲", "label": "Critical"},
    "serious": {"color": "#ec835a", "icon": "◆", "label": "Serious"},
    "warning": {"color": "#fab219", "icon": "!", "label": "Warning"},
    "good": {"color": "#0ca30c", "icon": "✓", "label": "No spatial flags"},
}
INK = "#0b0b0b"
INK_2 = "#52514e"
PLANNED_BLUE = "#2a78d6"
NEUTRAL = "#8a8983"
QUAD_ON = "#26323f"

# The map is saved as outputs/transect_map.html, beside the dashboard folder.
DASHBOARD_DIR = "dashboard/"

# Survey-area and stratum outlines. No official boundary is supplied, so these are drawn around the
# planned plot locations and labelled as such. Colours avoid the status and planned-location palette.
AREA_BUFFER_M = 600
STRATUM_BUFFER_M = 250
STRATUM_COLOURS = ["#0f766e", "#7c3aed", "#9a3412", "#1d4ed8"]
REFERENCE_TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Andrew's monotone chain; points are (x, y) in metres."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts
    cross = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def outline_around(lats, lons, buffer_m: float) -> list[list[float]]:
    """Convex outline enclosing every point by at least ``buffer_m``, as [[lat, lon], ...].

    Each point is replaced by a 24-sided circle before the hull is taken, which rounds the corners.
    Uses a local equirectangular projection, accurate to well under a metre over a few kilometres.
    """
    lat0 = float(np.mean(lats))
    m_lat, m_lon = 111_320.0, 111_320.0 * np.cos(np.radians(lat0))
    angles = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    pts = [(lo * m_lon + buffer_m * np.cos(a), la * m_lat + buffer_m * np.sin(a))
           for la, lo in zip(lats, lons) for a in angles]
    return [[y / m_lat, x / m_lon] for x, y in _convex_hull(pts)]


def _label_spot(ring: list[list[float]], lats, lons, min_width_m: float = 2500,
                east_gap_m: float = AREA_BUFFER_M - STRATUM_BUFFER_M + 150) -> tuple[list[float], str]:
    """Where to name an outline: the open interior point farthest from plots and edges, or, for a
    narrow outline, east of it at mid-height, clear of the survey-area outline.
    Returns ([lat, lon], 'inside' | 'east')."""
    lat0 = float(np.mean(lats))
    m_lat, m_lon = 111_320.0, 111_320.0 * np.cos(np.radians(lat0))
    poly = np.array([(p[1] * m_lon, p[0] * m_lat) for p in ring])
    width = poly[:, 0].max() - poly[:, 0].min()
    if width < min_width_m:
        mid_lat = (poly[:, 1].min() + poly[:, 1].max()) / 2 / m_lat
        return [mid_lat, poly[:, 0].max() / m_lon + east_gap_m / m_lon], "east"
    plots = np.column_stack([np.asarray(lons) * m_lon, np.asarray(lats) * m_lat])
    edges = list(zip(poly, np.roll(poly, -1, axis=0)))

    def inside(x, y):
        return all((b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0]) >= 0 for a, b in edges)  # hull is CCW

    def edge_dist(x, y):
        best = np.inf
        for a, b in edges:
            ab, ap = b - a, np.array([x, y]) - a
            t = np.clip(ap @ ab / (ab @ ab), 0, 1)
            best = min(best, np.hypot(*(ap - t * ab)))
        return best

    xs = np.linspace(poly[:, 0].min(), poly[:, 0].max(), 40)
    ys = np.linspace(poly[:, 1].min(), poly[:, 1].max(), 40)
    score, spot = max((min(np.hypot(*(plots - (x, y)).T).min(), 2 * edge_dist(x, y)), (x, y))
                      for x in xs for y in ys if inside(x, y))
    return [spot[1] / m_lat, spot[0] / m_lon], "inside"


# Share of a transect's quadrats lying off the registered line that triggers each priority.
CRITICAL_SHARE = 0.5
SERIOUS_SHARE = 0.25


def priority_rules(qa: dict) -> dict[str, str]:
    """Plain-language rule behind each review priority, built from the QA parameters."""
    lo, hi = qa["transect_length_m"]
    return {
        "critical": f"{CRITICAL_SHARE:.0%} or more of the quadrats lie off the registered line",
        "serious": f"{SERIOUS_SHARE:.0%} or more lie off the line, or the midpoint is more than "
                   f"{qa['midpoint_max_offset_m']:g} m from the planned point",
        "warning": f"transect length outside {lo:g}–{hi:g} m, or any quadrat off the line",
        "good": "none of the above",
    }


def _esc(value) -> str:
    return html.escape("" if value is None or (isinstance(value, float) and np.isnan(value)) else str(value))


def _short(plot_name: str) -> str:
    return plot_name.rsplit("_", 1)[-1]


def _fmt_time(raw: str) -> str:
    if not isinstance(raw, str) or len(raw) < 16:
        return "—"
    ts = pd.Timestamp(raw[:19])
    return f"{ts.day} {ts:%b %Y}, {ts:%H:%M} (device {raw[-6:]})"


def review_priority(off_share: float, length_flag: bool, midpoint_flag: bool) -> tuple[str, str]:
    """Spatial review priority and its reason for one transect. Shared by the map and the dashboard."""
    off_share = 0.0 if pd.isna(off_share) else float(off_share)
    if off_share >= CRITICAL_SHARE:
        return "critical", "Most quadrats lie off the registered line"
    if off_share >= SERIOUS_SHARE or midpoint_flag:
        reason = "Many quadrats lie off the registered line" if off_share >= 0.25 else "Midpoint far from the planned point"
        return "serious", reason
    if length_flag or off_share > 0:
        reason = "Transect length outside 45–55 m" if length_flag else "Some quadrats lie off the registered line"
        return "warning", reason
    return "good", "No spatial review flags"


def transect_priorities(transects, plot_summary, flags, qa) -> pd.DataFrame:
    """Review priority of every transect with recorded coordinates.

    Inputs are the notebook 02 tables (or their CSV exports): transect geometry,
    plot summary with ``flagged_share``, QA flags and QA parameters.
    """
    accepted = plot_summary[plot_summary["include_in_analysis"].astype(bool)].set_index("plot_name")
    plot_flags = flags[flags["level"] == "plot"]
    lo, hi = qa["transect_length_m"]
    rows = []
    for t in transects.dropna(subset=["a_lat", "m_lat", "b_lat"]).itertuples():
        rules = set(plot_flags.loc[plot_flags["plot_name"] == t.plot_name, "rule_id"])
        share = accepted.at[t.plot_name, "flagged_share"] if t.plot_name in accepted.index else None
        status, reason = review_priority(share, "P01" in rules or not (lo <= t.length_m <= hi), "P03" in rules)
        rows.append({"plot_name": t.plot_name, "priority": status, "reason": reason})
    return pd.DataFrame(rows, columns=["plot_name", "priority", "reason"])


def plot_review_table(plot_summary, transects, flags, effort, qa) -> pd.DataFrame:
    """One row per non-rejected submission: effort, provisional richness, flags, geometry and review priority.

    Uses the same priority rule as the map and dashboard. Values are reported as recorded; nothing is corrected.
    """
    acc = plot_summary[plot_summary["include_in_analysis"].astype(bool)]
    prio = transect_priorities(transects, plot_summary, flags, qa)
    t = (acc.merge(prio, on="plot_name", how="left")
         .merge(transects[["plot_name", "length_m", "bearing_deg"]], on="plot_name", how="left")
         .merge(effort[["plot_name", "expected_new_taxa_in_final_up_to_5_quadrats"]], on="plot_name", how="left"))
    order = {k: i for i, k in enumerate(["critical", "serious", "warning", "good"])}
    t = t.assign(_rank=t["priority"].map(order).fillna(len(order))).sort_values(["_rank", "flagged_quadrats", "plot_name"],
                                                                              ascending=[True, False, True])
    return pd.DataFrame({
        "Plot": t["plot_name"].map(_short),
        "Review priority": t["priority"].map(lambda p: STATUS[p]["label"] if p in STATUS else "No transect"),
        "Quadrats": t["actual_quadrats"].astype(int),
        "With herbs": t["actual_quadrats_with_herbs"].astype(int),
        "Provisional richness": t["provisional_richness"].round(0).astype("Int64"),
        "Errors": t["error"].astype(int), "Warnings": t["warning"].astype(int), "Info": t["info"].astype(int),
        "Quadrats off the line": t["flagged_quadrats"].astype("Int64"),
        "Median distance (m)": t["median_distance_m"].round(1),
        "Length (m)": t["length_m"].round(0).astype("Int64"),
        "Bearing (°)": t["bearing_deg"].round(0).astype("Int64"),
        "New taxa, last 5 quadrats": t["expected_new_taxa_in_final_up_to_5_quadrats"].round(1),
    })


def _chip(status: str, text: str, label: str | None = None) -> str:
    s = STATUS[status]
    return (f'<div class="nc-chip"><span class="nc-ic" style="background:{s["color"]}">{s["icon"]}</span>'
            f'<span><b>{label or s["label"]}</b> · {_esc(text)}</span></div>')


def _row(label: str, value: str, ref: str = "", flagged: bool = False) -> str:
    mark = '<span class="nc-dot"></span>' if flagged else ""
    cls = ' class="nc-flag"' if flagged else ""
    ref_html = f'<div class="nc-ref">{ref}</div>' if ref else ""
    return f"<tr{cls}><th>{label}</th><td>{mark}{value}{ref_html}</td></tr>"


def _transect_card(t, status, reason, sub, eff, sev, n_rejected, qa) -> str:
    lo, hi = qa["transect_length_m"]
    length_flag = not (lo <= t.length_m <= hi)
    mid_flag = t.midpoint_offset_m > qa["midpoint_max_offset_m"]
    rot_flag = t.ns_deviation_deg > qa["bearing_tolerance_deg"]
    rows = [
        _row("Length", f"{t.length_m:.1f} m", f"SOP 50 m · review outside {lo}–{hi} m", length_flag),
        _row("Bearing", f"{t.bearing_deg:.0f}°", f"{t.ns_deviation_deg:.0f}° off north–south", rot_flag),
        _row("Midpoint shift", f"{t.midpoint_offset_m:.1f} m", f"SOP limit {qa['midpoint_max_offset_m']} m", mid_flag),
    ]
    if sub is not None:
        off = int(sub.flagged_quadrats) if pd.notna(sub.flagged_quadrats) else 0
        n_q = int(sub.actual_quadrats)
        rows.append(_row("Off-line quadrats", f"{off} of {n_q}",
                         f"median {sub.median_distance_m:.1f} m from line", off > 0))
        rich = f"{sub.provisional_richness:.0f} taxa" if pd.notna(sub.provisional_richness) else "—"
        tail = (f"+{eff.expected_new_taxa_in_final_up_to_5_quadrats:.1f} in last 5 quadrats"
                if eff is not None else "")
        rows.append(_row("Richness", rich, tail))
    meta = []
    if sub is not None:
        meta.append(f"{_esc(sub.recorder)} · {_fmt_time(sub.start_time)} · {sub.duration_min:.0f} min")
    if n_rejected:
        meta.append(f"+{n_rejected} rejected submission (excluded from ecology)")
    qa_line = (f"QA flags: <b>{sev.get('error', 0)}</b> error · <b>{sev.get('warning', 0)}</b> warning · "
               f"<b>{sev.get('info', 0)}</b> info")
    return (
        '<div class="nc">'
        f'<div class="nc-hd"><div class="nc-t">Plot {_short(t.plot_name)}</div>'
        f'<div class="nc-s">{_esc(t.plot_name)} · {_esc(t.sample_status)}</div></div>'
        f"{_chip(status, reason)}"
        f'<table class="nc-g">{"".join(rows)}</table>'
        + "".join(f'<div class="nc-m">{m}</div>' for m in meta)
        + f'<div class="nc-f">{qa_line}</div></div>'
    )


def _flag_list(plot_flags: pd.DataFrame) -> str:
    if plot_flags.empty:
        return '<div class="nc-fl"><div class="nc-flh">No QA flags for this plot</div></div>'
    order = {"error": 0, "warning": 1, "info": 2}
    g = (plot_flags.groupby(["severity", "rule_id", "message"]).size().rename("n").reset_index()
         .assign(o=lambda d: d["severity"].map(order)).sort_values(["o", "rule_id"]))
    items = "".join(
        f'<li><span class="nc-sev nc-{_esc(r.severity)}">{_esc(r.severity)}</span>'
        f'<span class="nc-rule">{_esc(r.rule_id)}</span> {_esc(r.message)}'
        f'{" ×" + str(r.n) if r.n > 1 else ""}</li>'
        for r in g.itertuples()
    )
    return f'<div class="nc-fl"><div class="nc-flh">All QA flags for this plot</div><ul>{items}</ul></div>'


def _quadrat_card(q, allowance: float, gps_max: float) -> str:
    off = q.distance_to_transect_m > allowance
    status = "serious" if off else "good"
    text = (f"{q.distance_to_transect_m:.1f} m from the registered line" if off
            else "Within the belt allowance")
    position = "Beyond a transect endpoint" if bool(q.beyond_endpoint) else "Alongside the transect"
    rows = [
        _row("Distance to line", f"{q.distance_to_transect_m:.1f} m", f"allowance {allowance:.1f} m", off),
        _row("GPS accuracy", f"±{q.gps_accuracy_m:.1f} m", f"SOP ≤ {gps_max:.0f} m", q.gps_accuracy_m > gps_max),
        _row("Position", position, ""),
        _row("Herbs present", _esc(q.herbs_present), ""),
        _row("Species entries", f"{int(q.n_species_listed)}", ""),
    ]
    sub = "rejected submission" if q.review_state == "rejected" else "accepted submission"
    chip = _chip(status, text, "Off line" if off else "On line")
    return (
        '<div class="nc nc-sm">'
        f'<div class="nc-hd"><div class="nc-t">Plot {_short(q.plot_name)} · Quadrat {int(q.quadrat_number)}</div>'
        f'<div class="nc-s">{sub}</div></div>{chip}'
        f'<table class="nc-g">{"".join(rows)}</table></div>'
    )


def _planned_card(title: str, subtitle: str, body: str) -> str:
    return (f'<div class="nc nc-sm"><div class="nc-hd"><div class="nc-t">{title}</div>'
            f'<div class="nc-s">{subtitle}</div></div><div class="nc-m">{body}</div></div>')


CSS = """
<style>
:root { --ink:#0b0b0b; --ink2:#52514e; --ink3:#77766f; --surface:#fcfcfb; --line:#e4e3de; }
html, body { font-family: Inter, "Segoe UI", system-ui, -apple-system, sans-serif; }
.leaflet-container { background:#e9e8e3; font-family: inherit; }
.leaflet-tooltip.ns-tip, .ns-pop .leaflet-popup-content-wrapper {
  padding:0; border:0; border-radius:12px; background:var(--surface);
  box-shadow:0 10px 30px rgba(15,15,10,.18), 0 1px 3px rgba(15,15,10,.12); color:var(--ink); }
.leaflet-tooltip.ns-tip:before { display:none; }
.ns-pop .leaflet-popup-content { margin:0; width:auto !important; }
.ns-pop .leaflet-popup-tip { background:var(--surface); }
.nc { width:300px; padding:12px 14px 10px; font-size:12px; line-height:1.4; white-space:normal; }
.nc-sm { width:270px; }
.nc-hd { margin-bottom:8px; }
.nc-t { font-size:15px; font-weight:650; letter-spacing:-.01em; }
.nc-s { color:var(--ink3); font-size:11px; margin-top:1px; }
.nc-chip { display:flex; gap:8px; align-items:flex-start; padding:7px 9px; border-radius:8px;
  background:#f3f2ee; margin-bottom:8px; color:var(--ink); }
.nc-ic { flex:0 0 18px; height:18px; border-radius:50%; color:#fff; font-size:10px; font-weight:700;
  display:inline-flex; align-items:center; justify-content:center; text-shadow:0 0 2px rgba(0,0,0,.35); }
.nc-g { width:100%; border-collapse:collapse; }
.nc-g th { text-align:left; font-weight:500; color:var(--ink2); padding:4px 10px 4px 0; white-space:nowrap; vertical-align:top; }
.nc-g th { width:42%; }
.nc-g td { font-weight:600; padding:4px 0; vertical-align:top; font-variant-numeric:tabular-nums; }
.nc-ref { font-weight:400; color:var(--ink3); font-size:11px; margin-top:1px; }
.nc-g tr + tr th, .nc-g tr + tr td { border-top:1px solid var(--line); }
.nc-dot { display:inline-block; width:7px; height:7px; border-radius:50%; background:#ec835a; margin-right:5px; vertical-align:1px; }
.nc-m { color:var(--ink2); margin-top:7px; font-size:11px; }
.nc-f { margin-top:8px; padding-top:7px; border-top:1px solid var(--line); color:var(--ink2); font-size:11px; }
.nc-fl { border-top:1px solid var(--line); margin:0 14px 12px; padding-top:8px; font-size:11px; }
.nc-flh { font-weight:650; margin-bottom:5px; }
.nc-fl ul { margin:0; padding:0; list-style:none; max-height:170px; overflow:auto; }
.nc-fl li { padding:3px 0; color:var(--ink2); }
.nc-sev { display:inline-block; min-width:68px; font-size:10px; font-weight:650; text-transform:uppercase; letter-spacing:.03em; color:var(--ink); }
.nc-sev:before { content:""; display:inline-block; width:7px; height:7px; border-radius:50%; margin-right:4px; vertical-align:0; }
.nc-error:before { background:#d03b3b; } .nc-warning:before { background:#fab219; } .nc-info:before { background:#8a8983; }
.nc-rule { font-family: ui-monospace, Consolas, monospace; font-size:10px; color:var(--ink3); margin-right:3px; }
.ns-label { background:none; border:0; }
.ns-label span { display:inline-block; transform:translate(10px,-50%); padding:1px 6px; border-radius:9px;
  background:rgba(252,252,251,.92); color:var(--ink); font-size:11px; font-weight:650; white-space:nowrap;
  box-shadow:0 1px 3px rgba(0,0,0,.25); }
.ns-x { background:none; border:0; }
.ns-x div { width:16px; height:16px; color:#d03b3b; font-size:18px; font-weight:800; line-height:16px; text-align:center;
  text-shadow:0 0 3px #fff, 0 0 3px #fff; }
.ns-ref { filter:brightness(.5) contrast(1.8); }
.ns-area, .ns-stratum { background:none; border:0; }
.ns-area div, .ns-stratum div { position:absolute; left:0; top:0; white-space:nowrap; text-align:center; pointer-events:none;
  text-shadow:0 0 3px #fff, 0 0 3px #fff, 0 0 6px #fff, 0 0 6px #fff; }
.ns-area div { transform:translate(-50%, calc(-100% - 6px)); color:var(--ink); }
.ns-area b { display:block; font-size:16px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }
.ns-area span { display:block; font-size:11px; font-weight:600; color:var(--ink2); }
.ns-inside div { transform:translate(-50%, -50%); }
.ns-east div { transform:translate(0, -50%); text-align:left; }
.ns-stratum b { display:block; font-size:13px; font-weight:800; letter-spacing:.04em; text-transform:uppercase; }
.ns-stratum span { display:block; font-size:10.5px; font-weight:600; }
.z-lt14 .ns-label { display:none; }
.z-lt15 .ns-quad, .z-lt15 .ns-link { display:none; }
.ns-panel, .ns-legend { position:fixed; z-index:1000; background:rgba(252,252,251,.97); color:var(--ink);
  border-radius:14px; box-shadow:0 10px 30px rgba(15,15,10,.16), 0 1px 3px rgba(15,15,10,.1); }
.ns-panel { top:12px; left:12px; width:300px; max-width:calc(100% - 24px); padding:14px 16px 12px; font-size:12px; }
.ns-panel h1 { font-size:16px; margin:0; letter-spacing:-.01em; }
.ns-back { display:flex; gap:6px; margin:-2px 0 10px; }
.ns-back a { font-size:11.5px; font-weight:600; color:#2647a0; text-decoration:none; padding:3px 9px; border-radius:7px;
  border:1px solid #cdd9ee; background:#f2f6fc; }
.ns-back a:hover { background:#e4ecf9; }
.ns-panel .sub { color:var(--ink3); font-size:11px; margin:2px 0 10px; }
.ns-kpis { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:10px; }
.ns-kpi { background:#f3f2ee; border-radius:9px; padding:7px 9px; }
.ns-kpi b { display:block; font-size:18px; letter-spacing:-.02em; font-variant-numeric:tabular-nums; }
.ns-kpi span { color:var(--ink2); font-size:11px; }
.ns-note { color:var(--ink2); font-size:11px; margin:0 0 10px; }
.ns-ctrl { display:flex; gap:6px; }
.ns-ctrl select, .ns-ctrl button { font:inherit; font-size:12px; border:1px solid var(--line); border-radius:8px;
  background:#fff; color:var(--ink); padding:5px 8px; }
.ns-ctrl select { flex:1; min-width:0; }
.ns-ctrl button { cursor:pointer; }
.ns-legend { left:12px; bottom:56px; padding:10px 12px; font-size:11px; width:230px;
  max-height:calc(100vh - 470px); min-height:110px; overflow:auto; }
.ns-legend h2 { font-size:11px; margin:0 0 6px; text-transform:uppercase; letter-spacing:.05em; color:var(--ink2); }
.ns-legend .it { display:flex; align-items:center; gap:7px; margin:3px 0; }
.ns-legend .sw { width:16px; display:inline-flex; justify-content:center; }
.ns-legend .sep { border-top:1px solid var(--line); margin:7px 0; }
.ns-legend .rule { color:var(--ink3); font-size:10px; margin-top:6px; }
.leaflet-control-layers { border-radius:12px !important; border:0 !important; box-shadow:0 10px 30px rgba(15,15,10,.16) !important; font-size:12px; }
@media (max-width: 700px) { .ns-legend { display:none; } .ns-panel { width:auto; right:12px; } }
</style>
"""


class _MapBehaviour(MacroElement):
    """Zoom-dependent detail, plot picker and reset button."""

    _template = Template("""
    {% macro script(this, kwargs) %}
    (function () {
      var map = {{ this._parent.get_name() }};
      L.control.zoom({position: 'bottomright'}).addTo(map);
      var el = map.getContainer();
      var PAD_TL = window.innerWidth > 700 ? [330, 30] : [20, 20];
      var PAD_BR = window.innerWidth > 700 ? [230, 40] : [20, 20];  // room for outline names on the right
      map.fitBounds({{ this.all_json }}, {paddingTopLeft: PAD_TL, paddingBottomRight: PAD_BR});
      function upd() { var z = map.getZoom(); el.classList.toggle('z-lt14', z < 14); el.classList.toggle('z-lt15', z < 15); }
      map.on('zoomend', upd); upd();
      var bounds = {{ this.bounds_json }}, all = {{ this.all_json }};
      var sel = document.getElementById('ns-plot'), reset = document.getElementById('ns-reset');
      if (sel) sel.addEventListener('change', function () {
        var b = bounds[this.value]; if (b) map.flyToBounds(b, {paddingTopLeft: PAD_TL, paddingBottomRight: PAD_BR, maxZoom: 19, duration: 1.2});
      });
      if (reset) reset.addEventListener('click', function () {
        map.flyToBounds(all, {paddingTopLeft: PAD_TL, paddingBottomRight: PAD_BR, duration: 1.0}); if (sel) sel.value = '';
      });
    })();
    {% endmacro %}
    """)

    def __init__(self, bounds: dict, all_bounds: list):
        super().__init__()
        self._name = "MapBehaviour"
        self.bounds_json = json.dumps(bounds)
        self.all_json = json.dumps(all_bounds)


def _add_outlines(m, cent: pd.DataFrame, cov: pd.DataFrame, area_title: str, area_sub: str) -> list[tuple[str, str]]:
    """Draw the survey-area and per-stratum outlines with permanent names; return (colour, label) for the legend."""
    group = folium.FeatureGroup(name="Survey area & strata outlines", show=True).add_to(m)
    pts = cent.dropna(subset=["lat", "lon"])
    surveyed = cov.set_index("plot_name")["n_submissions"].fillna(0).gt(0)

    def draw(ring, colour, weight, dash, tip):
        # Light tint, then a white casing under the coloured line so it stays visible on every basemap.
        # Only the line itself carries the tooltip; the tint stays click-through.
        folium.Polygon(ring, stroke=False, fill=True, fill_color=colour, fill_opacity=0.04, interactive=False).add_to(group)
        folium.Polygon(ring, color="#ffffff", weight=weight + 4, opacity=0.95, fill=False, interactive=False).add_to(group)
        folium.Polygon(ring, color=colour, weight=weight, dash_array=dash, fill=False,
                       tooltip=folium.Tooltip(tip, sticky=True)).add_to(group)

    def label(at, cls, html_):
        folium.Marker(at, icon=folium.DivIcon(html=html_, class_name=cls, icon_size=(0, 0), icon_anchor=(0, 0)),
                      interactive=False).add_to(group)

    legend = []
    area_ring = outline_around(pts["lat"], pts["lon"], AREA_BUFFER_M)
    draw(area_ring, INK, 3.5, None, f"<b>{_esc(area_title)}</b><br>Outline drawn {AREA_BUFFER_M} m around all "
                                    f"{len(pts)} planned plot locations; not an official boundary.")
    label(max(area_ring, key=lambda p: p[0]), "ns-area", f"<div><b>{_esc(area_title)}</b><span>{_esc(area_sub)}</span></div>")
    legend.append((INK, f"Survey area: {area_title}"))
    for i, (stratum, g) in enumerate(pts.groupby("stratum_label")):
        colour = STRATUM_COLOURS[i % len(STRATUM_COLOURS)]
        n_surveyed = int(surveyed.reindex(g["choice_name"]).fillna(False).sum())
        name = f"{str(stratum).capitalize()} stratum"
        counts = f"{len(g)} planned plots · {n_surveyed} surveyed"
        ring = outline_around(g["lat"], g["lon"], STRATUM_BUFFER_M)
        draw(ring, colour, 3, "10 6", f"<b>{_esc(name)}</b><br>{counts}<br>Outline drawn {STRATUM_BUFFER_M} m around "
                                      "its planned plot locations; not an official boundary.")
        spot, side = _label_spot(ring, g["lat"], g["lon"])
        label(spot, f"ns-stratum ns-{side}", f'<div style="color:{colour}"><b>{_esc(name)}</b><span>{counts}</span></div>')
        legend.append((colour, f"{name} ({counts})"))
    return legend


def build_transect_map(transects, qgeom, centroids, coverage, flags, survey, plot_summary, effort, qa,
                       title="Herbaceous transect review", areas=None):
    """Return a Folium map of registered transects, quadrats and planned locations.

    All inputs are the notebook 02 tables of the same names. Coordinates are drawn as recorded.
    ``areas`` (the raw areas table) is optional and only supplies the full area name for its label.
    """
    cent = centroids.assign(xy=centroids["geometry"].apply(parse_point))
    cent["lat"], cent["lon"] = cent["xy"].str[0], cent["xy"].str[1]
    cov = coverage.merge(cent[["__id", "lat", "lon"]], left_on="centroid_id", right_on="__id", how="left")

    accepted = plot_summary[plot_summary["include_in_analysis"]].merge(
        survey[["submission_key", "recorder", "start_time", "device"]], on="submission_key", how="left")
    acc_by_plot = accepted.set_index("plot_name")
    eff_by_plot = effort.set_index("plot_name")
    rejected_n = plot_summary[~plot_summary["include_in_analysis"]].groupby("plot_name").size()
    sev_by_plot = flags.groupby(["plot_name", "severity"]).size().unstack(fill_value=0)
    priority = transect_priorities(transects, plot_summary, flags, qa).set_index("plot_name")

    mapped = transects.dropna(subset=["a_lat", "m_lat", "b_lat"]).merge(
        coverage[["centroid_id", "sample_status"]], on="centroid_id", how="left")
    records = []
    for t in mapped.itertuples():
        sub = acc_by_plot.loc[t.plot_name] if t.plot_name in acc_by_plot.index else None
        records.append((t, sub, priority.at[t.plot_name, "priority"], priority.at[t.plot_name, "reason"]))

    lats = pd.concat([cov["lat"], mapped["m_lat"]]).dropna()
    lons = pd.concat([cov["lon"], mapped["m_lon"]]).dropna()
    all_bounds = [[lats.min(), lons.min()], [lats.max(), lons.max()]]

    m = folium.Map(location=[lats.mean(), lons.mean()], tiles=None, zoom_control=False,
                   control_scale=True, max_zoom=20)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        attr="Basemap © Esri, HERE, Garmin, OpenStreetMap contributors", name="Light", max_zoom=20, max_native_zoom=16,
    ).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Imagery © Esri, Maxar, Earthstar Geographics", name="Satellite", max_zoom=20, max_native_zoom=19,
        show=False,
    ).add_to(m)
    # OSM's own tile servers block requests without a Referer, which a map opened from disk never sends.
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Basemap © Esri, HERE, Garmin, OpenStreetMap contributors", name="Streets", max_zoom=20, max_native_zoom=19,
        show=False,
    ).add_to(m)
    # County borders and town names; Esri draws them only up to about zoom 12. Darkened via .ns-ref.
    folium.TileLayer(tiles=REFERENCE_TILES, attr="Boundaries and places © Esri", name="Boundaries & place names (Esri)",
                     overlay=True, show=True, max_zoom=20, max_native_zoom=19, className="ns-ref").add_to(m)

    project = survey["survey_begin-project_label"].iloc[0]
    area = survey["survey_begin-area_label"].iloc[0]
    area_name = None
    if areas is not None and "label" in areas and area in set(areas["label"]):
        area_name = areas.set_index("label").at[area, "area_name"]
    area_title = f"{area_name} ({area})" if area_name else f"Area {area}"
    outline_legend = _add_outlines(m, cent, cov, area_title, f"Survey area · {project}")

    fg_planned = folium.FeatureGroup(name="Planned locations", show=True).add_to(m)
    fg_link = folium.FeatureGroup(name="Planned → registered midpoint", show=True).add_to(m)
    fg_quads = folium.FeatureGroup(name="Quadrats (accepted submissions)", show=True).add_to(m)
    fg_rejq = folium.FeatureGroup(name="Quadrats (rejected submissions)", show=False).add_to(m)
    fg_lines = folium.FeatureGroup(name="Registered transects", show=True).add_to(m)
    fg_labels = folium.FeatureGroup(name="Plot labels", show=True).add_to(m)

    # Planned locations without a registered transect.
    surveyed = set(mapped["plot_name"])
    for c in cov.itertuples():
        if pd.isna(c.lat) or c.plot_name in surveyed:
            continue
        if c.is_viable == "no":
            card = _planned_card(f"Plot {_short(c.plot_name)}", f"{_esc(c.plot_name)} · {c.sample_status}",
                                 f"<b>Registered non-viable.</b> {_esc(c.establishment_notes) or 'No reason recorded'}. "
                                 "No transect or survey exists for this location.")
            folium.Marker([c.lat, c.lon], icon=folium.DivIcon(html="<div>✕</div>", class_name="ns-x",
                                                              icon_size=(16, 16), icon_anchor=(8, 8)),
                          tooltip=folium.Tooltip(card, sticky=True, class_name="ns-tip", opacity=1)).add_to(fg_planned)
        elif c.sample_status == "primary":
            card = _planned_card(f"Plot {_short(c.plot_name)}", f"{_esc(c.plot_name)} · primary",
                                 "<b>Planned but not registered or surveyed.</b> A gap in spatial coverage.")
            folium.CircleMarker([c.lat, c.lon], radius=7, color=PLANNED_BLUE, weight=2.5, fill=True,
                                fill_color="#ffffff", fill_opacity=0.85,
                                tooltip=folium.Tooltip(card, sticky=True, class_name="ns-tip", opacity=1)).add_to(fg_planned)
        else:
            card = _planned_card(f"Plot {_short(c.plot_name)}", f"{_esc(c.plot_name)} · backup",
                                 "Backup location, not used.")
            folium.CircleMarker([c.lat, c.lon], radius=4, color="#ffffff", weight=1, fill=True,
                                fill_color=NEUTRAL, fill_opacity=0.9,
                                tooltip=folium.Tooltip(card, sticky=True, class_name="ns-tip", opacity=1)).add_to(fg_planned)

    # Quadrats, coloured by whether they fall within the belt allowance.
    for q in qgeom.dropna(subset=["lat", "lon"]).itertuples():
        allowance = qa["belt_half_width_m"] + q.gps_accuracy_m + qa["gps_accuracy_max_m"]
        off = q.distance_to_transect_m > allowance
        rejected = q.review_state == "rejected"
        colour = NEUTRAL if rejected else (STATUS["serious"]["color"] if off else QUAD_ON)
        folium.CircleMarker(
            [q.lat, q.lon], radius=4.5 if off else 3.5, color="#ffffff", weight=1.2, fill=True,
            fill_color=colour, fill_opacity=1, class_name="ns-quad",
            tooltip=folium.Tooltip(_quadrat_card(q, allowance, qa["gps_accuracy_max_m"]),
                                   sticky=True, class_name="ns-tip", opacity=1),
        ).add_to(fg_rejq if rejected else fg_quads)

    bounds = {}
    for t, sub, status, reason in records:
        colour = STATUS[status]["color"]
        sev = sev_by_plot.loc[t.plot_name].to_dict() if t.plot_name in sev_by_plot.index else {}
        eff = eff_by_plot.loc[t.plot_name] if t.plot_name in eff_by_plot.index else None
        card = _transect_card(t, status, reason, sub, eff, sev, int(rejected_n.get(t.plot_name, 0)), qa)
        popup_html = card + _flag_list(flags[flags["plot_name"] == t.plot_name])
        line = [[t.a_lat, t.a_lon], [t.m_lat, t.m_lon], [t.b_lat, t.b_lon]]

        # Planned point and displacement to the registered midpoint.
        folium.PolyLine([[t.c_lat, t.c_lon], [t.m_lat, t.m_lon]], color=INK_2, weight=1.5, dash_array="4 4",
                        opacity=0.9, class_name="ns-link").add_to(fg_link)
        folium.CircleMarker([t.c_lat, t.c_lon], radius=3, color="#ffffff", weight=1, fill=True, fill_color=INK_2,
                            fill_opacity=1, class_name="ns-link",
                            tooltip=folium.Tooltip(_planned_card(
                                f"Planned point · Plot {_short(t.plot_name)}", _esc(t.plot_name),
                                f"Registered midpoint is <b>{t.midpoint_offset_m:.1f} m</b> away "
                                f"(SOP limit {qa['midpoint_max_offset_m']} m)."),
                                sticky=True, class_name="ns-tip", opacity=1)).add_to(fg_link)

        # Transect: white halo for contrast on any basemap, then the status line.
        folium.PolyLine(line, color="#ffffff", weight=9, opacity=0.9).add_to(fg_lines)
        tip = folium.Tooltip(card, sticky=True, class_name="ns-tip", opacity=1)
        pop = folium.Popup(popup_html, max_width=340, class_name="ns-pop")
        folium.PolyLine(line, color=colour, weight=5, opacity=1, tooltip=tip, popup=pop).add_to(fg_lines)
        for lat, lon, end in [(t.a_lat, t.a_lon, "A"), (t.b_lat, t.b_lon, "B")]:
            folium.CircleMarker([lat, lon], radius=3, color=colour, weight=2, fill=True, fill_color="#ffffff",
                                fill_opacity=1, tooltip=f"Plot {_short(t.plot_name)} · endpoint {end}").add_to(fg_lines)
        # Midpoint symbol keeps each plot visible at overview zoom, where a 50 m line is a few pixels.
        folium.CircleMarker([t.m_lat, t.m_lon], radius=7, color="#ffffff", weight=2, fill=True, fill_color=colour,
                            fill_opacity=1,
                            tooltip=folium.Tooltip(card, sticky=True, class_name="ns-tip", opacity=1),
                            popup=folium.Popup(popup_html, max_width=340, class_name="ns-pop")).add_to(fg_lines)
        folium.Marker([t.m_lat, t.m_lon], icon=folium.DivIcon(
            html=f"<span>{_short(t.plot_name)}</span>", class_name="ns-label", icon_size=(0, 0)),
            interactive=False).add_to(fg_labels)
        pq = qgeom[(qgeom["plot_name"] == t.plot_name) & qgeom["lat"].notna()]
        b_lat = [t.a_lat, t.b_lat, t.c_lat, t.m_lat, *pq["lat"]]
        b_lon = [t.a_lon, t.b_lon, t.c_lon, t.m_lon, *pq["lon"]]
        pad = 0.00008
        bounds[t.plot_name] = [[min(b_lat) - pad, min(b_lon) - pad], [max(b_lat) + pad, max(b_lon) + pad]]

    # Header panel with headline numbers computed from the inputs.
    n_primary = int((coverage["sample_status"] == "primary").sum())
    primary_surveyed = int(((coverage["sample_status"] == "primary") & (coverage["n_submissions"] > 0)).sum())
    not_registered = int(((coverage["sample_status"] == "primary") & coverage["is_viable"].isna()).sum())
    acc_q = qgeom[qgeom["review_state"].ne("rejected")]
    acc_allow = qa["belt_half_width_m"] + acc_q["gps_accuracy_m"] + qa["gps_accuracy_max_m"]
    off_q = int((acc_q["distance_to_transect_m"] > acc_allow).sum())
    viable = mapped[mapped["is_viable"] == "yes"]
    rotated = int((viable["ns_deviation_deg"] > qa["bearing_tolerance_deg"]).sum())
    counts = pd.Series([r[2] for r in records]).value_counts()
    options = "".join(f'<option value="{_esc(t.plot_name)}">Plot {_short(t.plot_name)} — '
                      f'{STATUS[s]["label"].lower()}</option>'
                      for t, _, s, _ in sorted(records, key=lambda r: r[0].plot_name))
    panel = f"""
    <div class="ns-panel">
      <nav class="ns-back" aria-label="Back to the dashboard"><a href="{DASHBOARD_DIR}vegetation.html">← Vegetation review</a><a href="{DASHBOARD_DIR}index.html">Overview</a></nav>
      <h1>{_esc(title)}</h1>
      <div class="sub">{_esc(project)} · area {_esc(area)} · recorded positions, uncorrected</div>
      <div class="ns-kpis">
        <div class="ns-kpi"><b>{primary_surveyed}/{n_primary}</b><span>primary plots surveyed</span></div>
        <div class="ns-kpi"><b>{not_registered}</b><span>primaries never registered</span></div>
        <div class="ns-kpi"><b>{off_q}/{len(acc_q)}</b><span>accepted quadrats off the line</span></div>
        <div class="ns-kpi"><b>{rotated}/{len(viable)}</b><span>transects rotated &gt;{qa['bearing_tolerance_deg']:.0f}° from <span style="white-space:nowrap">N–S</span></span></div>
      </div>
      <p class="ns-note">Median bearing {viable['bearing_deg'].median():.0f}°: transects run roughly east–west,
      against the SOP's north–south layout. Hover any symbol for detail; click a transect for its full QA flags.</p>
      <div class="ns-ctrl"><select id="ns-plot"><option value="">Go to plot…</option>{options}</select>
      <button id="ns-reset" type="button">All plots</button></div>
    </div>"""

    def sw_line(c):
        return f'<span class="sw"><svg width="16" height="8"><line x1="1" y1="4" x2="15" y2="4" stroke="{c}" stroke-width="4" stroke-linecap="round"/></svg></span>'

    def sw_dot(fill, stroke="#fff", r=5, sw=1.5):
        return f'<span class="sw"><svg width="14" height="14"><circle cx="7" cy="7" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/></svg></span>'

    status_items = "".join(
        f'<div class="it">{sw_line(STATUS[k]["color"])}<span><b>{STATUS[k]["icon"]}</b> {STATUS[k]["label"]} '
        f'({int(counts.get(k, 0))})</span></div>' for k in ["critical", "serious", "warning", "good"])
    rules = priority_rules(qa)
    rules_text = " ".join(f"{STATUS[k]['label']}: {rules[k]}." for k in ["critical", "serious", "warning"])
    dashes = ['stroke-dasharray="5 3"'] * len(outline_legend)
    dashes[0] = ""  # the area outline is solid, strata are dashed
    outline_items = "".join(
        f'<div class="it"><span class="sw"><svg width="16" height="8"><line x1="1" y1="4" x2="15" y2="4" stroke="{c}" '
        f'stroke-width="3" {dash}/></svg></span><span>{_esc(text)}</span></div>'
        for (c, text), dash in zip(outline_legend, dashes))
    legend = f"""
    <div class="ns-legend">
      <h2>Transect review priority</h2>{status_items}
      <div class="sep"></div>
      <div class="it">{sw_dot('#fff', PLANNED_BLUE, 5, 2.2)}<span>Primary, not registered</span></div>
      <div class="it"><span class="sw" style="color:#d03b3b;font-weight:800">✕</span><span>Registered non-viable</span></div>
      <div class="it">{sw_dot(NEUTRAL, '#fff', 3.5, 1)}<span>Backup, unused</span></div>
      <div class="it">{sw_dot(STATUS['serious']['color'])}<span>Quadrat off the line</span></div>
      <div class="it">{sw_dot(QUAD_ON)}<span>Quadrat on the line</span></div>
      <div class="it"><span class="sw"><svg width="16" height="8"><line x1="1" y1="4" x2="15" y2="4" stroke="{INK_2}" stroke-width="1.5" stroke-dasharray="3 3"/></svg></span><span>Planned point → midpoint</span></div>
      <div class="rule">{rules_text} Quadrats and links appear from zoom 15.</div>
      <div class="sep"></div>{outline_items}
      <div class="rule">Outlines are drawn around the planned plot locations (+{AREA_BUFFER_M} m area,
      +{STRATUM_BUFFER_M} m strata); they are not official boundaries.</div>
    </div>"""

    m.get_root().header.add_child(Element(CSS))
    m.get_root().html.add_child(Element(panel + legend))
    folium.LayerControl(collapsed=True, position="topright").add_to(m)
    Fullscreen(position="bottomright").add_to(m)
    minimap_tiles = folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        attr="Basemap © Esri", max_native_zoom=16,
    )
    MiniMap(tile_layer=minimap_tiles, position="bottomright", toggle_display=True,
            width=130, height=110, zoom_level_offset=-5).add_to(m)
    m.add_child(_MapBehaviour(bounds, all_bounds))
    return m