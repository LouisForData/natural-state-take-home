"""Static four-page results dashboard built from the notebooks' exported outputs.

Writes outputs/dashboard/index.html (overview), birds.html, vegetation.html and
files.html. Every number is read at build time from outputs/ plus two raw
reference tables (validation clips, planned centroids); nothing is recomputed
beyond counting and formatting. Pages are self-contained (inline CSS, JS and
SVG) and work offline, opened straight from disk.

Run after the notebooks:  python -m src.dashboard
"""
from __future__ import annotations

import html
import json
import math
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd

from src.dashboard_charts import (COLOUR, FUNNEL_KEY, PRIORITY_ORDER, SEVERITY_STATUS, calibration_svg, effort_svg,
                                  esc, funnel, ic, map_legend, plot_map_svg, rule_bars, short_plot as _short, swatch)
from src.transect_map import STATUS, priority_rules, transect_priorities

ASSETS = Path(__file__).with_name("dashboard_assets")

# thresholds.status -> (status colour key, decision label)
BIRD_DECISIONS = {
    "supported_exploratory_fit": ("good", "Released"),
    "pending_review_sparse_errors": ("warning", "Held for review"),
    "unsupported_fit": ("info", "Not estimable"),
    "unsupported_target_outside_validation_range": ("info", "Target out of range"),
}
BIRD_FILES = ["bird_thresholds.csv", "bird_label_summary.csv", "bird_validation_metrics.csv",
              "bird_checked_cutoff_evidence.csv", "bird_bin_weighted_precision.csv",
              "bird_firth_sensitivity.csv", "bird_validation_link_audit.csv", "birdnet_predictions_labelled.csv"]
VEG_FILES = ["veg_plot_summary.csv", "veg_qa_flags.csv", "veg_sampling_effort.csv", "veg_survey_summary.csv",
             "vegetation_transect_geometry.csv", "vegetation_plot_coverage.csv", "vegetation_project_patterns.csv",
             "vegetation_rule_catalogue.csv", "vegetation_qa_parameters.json"]

# ---------------------------------------------------------------------------- Files page catalogue
FILE_GROUPS = {
    "bird": ("Birds · labels", "BirdNET predictions turned into observations"),
    "bval": ("Birds · validation & sensitivity", "Evidence behind each threshold"),
    "veg": ("Vegetation · results", "Survey, plot and effort summaries"),
    "vqa": ("Vegetation · QA & audit", "Flags, rules and checks against the ODK forms"),
    "geo": ("Vegetation · transect geometry", "Positions as recorded, never corrected"),
    "maps": ("Maps", "Interactive review map and spatial interchange"),
    "figures": ("Figures", "Static charts saved by the notebooks"),
    "other": ("Other outputs", "Files without a description yet"),
}
FILE_DESCRIPTIONS = {
    "birdnet_predictions_labelled.csv": ("bird", "All BirdNET predictions with fitted threshold, probability correct and observation label."),
    "bird_label_summary.csv": ("bird", "Per species: predictions, fitted candidates, observations and rows sent for review."),
    "bird_thresholds.csv": ("bird", "Per-species logistic fit of correctness on confidence, and the resulting threshold."),
    "bird_findings.json": ("bird", "Machine-readable headline numbers behind the bird report."),
    "bird_validation_metrics.csv": ("bval", "Checked-sample precision per species with Wilson 95% interval."),
    "bird_validation_score_bins.csv": ("bval", "Validation sample by confidence bin, with prediction counts and weights."),
    "bird_bin_weighted_precision.csv": ("bval", "Precision re-weighted to the full prediction distribution, with missing-bin scenarios."),
    "bird_checked_cutoff_evidence.csv": ("bval", "Precision and one-sided 95% lower bound at each candidate cutoff."),
    "bird_raw_cutoff_diagnostic.csv": ("bval", "Checked precision and predictions retained at raw score cutoffs."),
    "bird_clipping_sensitivity.csv": ("bval", "How the score cutoff moves with the probability clipping epsilon."),
    "bird_firth_sensitivity.csv": ("bval", "Firth-penalised logistic fits as a check on separation."),
    "bird_validation_link_audit.csv": ("bval", "How many predictions each validation row matched."),
    "veg_survey_summary.csv": ("veg", "Survey-level headline counts: submissions, plots, quadrats, taxa and flag totals."),
    "veg_plot_summary.csv": ("veg", "One row per submission: quadrats, provisional richness and flag counts."),
    "veg_sampling_effort.csv": ("veg", "Species accumulation per plot: expected new taxa from further quadrats and an effort verdict."),
    "veg_observations_long.csv": ("veg", "Every species entry, one row per quadrat × species, with its source and analysis inclusion."),
    "vegetation_plot_coverage.csv": ("veg", "Planned centroids against registered and surveyed plots, with viability and rejections."),
    "vegetation_project_patterns.csv": ("veg", "Project-wide patterns, with affected records, denominator and interpretation."),
    "vegetation_findings.json": ("veg", "Machine-readable headline numbers behind the vegetation report."),
    "veg_qa_flags.csv": ("vqa", "Every QA flag: rule, severity, affected record, field, value and message."),
    "vegetation_rule_catalogue.csv": ("vqa", "The QA rules with severity, basis (SOP or analyst tolerance) and rule version."),
    "vegetation_qa_parameters.json": ("vqa", "Tolerances used by the QA rules: quadrat count, GPS accuracy, transect length, bearing."),
    "vegetation_integrity_checks.csv": ("vqa", "Join and key integrity checks with the number of problem rows."),
    "vegetation_form_calculation_audit.csv": ("vqa", "Quadrat counts stored by the ODK form compared with recomputed counts."),
    "vegetation_species_derivation_mismatches.csv": ("vqa", "Quadrats whose species display differs from the tidy reconstruction. Empty means all match."),
    "vegetation_form_catalogue.csv": ("vqa", "ODK form fields with type, constraints, relevance and calculations."),
    "vegetation_transect_geometry.csv": ("geo", "Recorded transect start, midpoint and end, with length, bearing and midpoint offset."),
    "vegetation_spatial_rollup.csv": ("geo", "Per-submission quadrat distances from the registered line and the share flagged."),
    "transect_map.html": ("maps", "Interactive transect review map. Basemap tiles need internet."),
    "transects.geojson": ("maps", "Transect lines as GeoJSON, ready for QGIS or any web map."),
    "figures/A2_prediction_eda.png": ("figures", "Prediction confidence by species"),
    "figures/A3_validation_outcomes.png": ("figures", "Validation outcomes"),
    "figures/A5_baseline_fits.png": ("figures", "Logistic baseline fits"),
    "figures/A7_probability_intervals.png": ("figures", "Probability-correct intervals"),
    "figures/B3_quadrat_eda.png": ("figures", "Quadrats per submission"),
    "figures/B9_sampling_effort.png": ("figures", "Sampling effort & accumulation"),
    "figures/B9_transect_map.png": ("figures", "Transect map (static)"),
}
PREVIEW_ROWS = 15
PREVIEW_JSON_CHARS = 3000
PREVIEW_CELL_CHARS = 120


# ---------------------------------------------------------------------------- small helpers
def _s(n: int) -> str:
    return "" if n == 1 else "s"


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def _all_of(n: int, d: int) -> str:
    return f"all {d}" if n == d else f"{n} of {d}"


def _veg_map(v: dict) -> str:
    return plot_map_svg(v["queue"], v["coverage"], v["centroids"])


def _plot_range(names) -> str:
    """'31–36' for a consecutive run, otherwise '05, 27 and 13'."""
    nums = sorted(int(_short(n)) for n in names)
    width = max(len(_short(n)) for n in names)
    if len(nums) > 2 and nums == list(range(nums[0], nums[-1] + 1)):
        return f"{nums[0]:0{width}d}–{nums[-1]:0{width}d}"
    return _and([f"{n:0{width}d}" for n in nums])


def _pct(x, digits=1) -> str:
    return "—" if pd.isna(x) else f"{x:.{digits}%}"


def _num(x, fmt=".3f", none="—") -> str:
    return none if pd.isna(x) else format(x, fmt)


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def chip(status: str, label: str, icon: str | None = None) -> str:
    return f'<span class="chip">{ic(status, icon)}{esc(label)}</span>'


def kpi(value: str, label: str, sub: str = "") -> str:
    sub_html = f'<div class="ks">{sub}</div>' if sub else ""
    return f'<div class="kpi"><div class="kv">{value}</div><div class="kl">{label}</div>{sub_html}</div>'


def of(n, d) -> str:
    return f"{n:,}<small>/{d:,}</small>"


def source(*files: str) -> str:
    return '<div class="src">Source: ' + ", ".join(f"<code>{f}</code>" for f in files) + "</div>"


def card(title: str, sub: str, body: str, sources: tuple = (), cls: str = "card") -> str:
    sub_html = f'<div class="cs">{sub}</div>' if sub else ""
    return f'<section class="{cls}"><h2>{title}</h2>{sub_html}{body}{source(*sources) if sources else ""}</section>'


def findings(items: list[tuple]) -> str:
    return '<ul class="fl">' + "".join(f"<li>{ic(*k) if isinstance(k, tuple) else ic(k)}<span>{t}</span></li>"
                                       for k, t in items) + "</ul>"


def notice(notebook: str, what: str) -> str:
    return (f'<div class="notice"><b>Run notebook {notebook} first.</b> The {what} outputs were not found in '
            f"<code>outputs/</code>, so these panels are empty. Rebuild with <code>python -m src.dashboard</code>.</div>")


def sortable_table(headers: list[tuple[str, bool]], rows: list[str], table_id: str = "") -> str:
    """headers: (label, numeric). rows: pre-rendered <tr> strings. Sort buttons are real <button>s."""
    ths = "".join(f'<th scope="col"{" class=n" if n else ""}><button type="button" class="sort">{h}</button></th>'
                  for h, n in headers)
    id_attr = f' id="{table_id}"' if table_id else ""
    return f'<div class="tw"><table class="sortable"{id_attr}><thead><tr>{ths}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def td(display, sort_value=None, numeric=True) -> str:
    v = "" if sort_value is None or pd.isna(sort_value) else f' data-v="{sort_value}"'
    return f'<td{" class=n" if numeric else ""}{v}>{display}</td>'


# ---------------------------------------------------------------------------- loading
def load_birds(root: Path) -> dict | None:
    out = root / "outputs"
    if not all((out / f).exists() for f in BIRD_FILES):
        return None
    read = lambda f, **kw: pd.read_csv(out / f, **kw)
    b = {"thr": read("bird_thresholds.csv").set_index("species"),
         "labels": read("bird_label_summary.csv").set_index("common_name"),
         "metrics": read("bird_validation_metrics.csv").set_index("species"),
         "evidence": read("bird_checked_cutoff_evidence.csv").set_index("species"),
         "binw": read("bird_bin_weighted_precision.csv").set_index("species"),
         "firth": read("bird_firth_sensitivity.csv").set_index("species"),
         "links": read("bird_validation_link_audit.csv"),
         "pred": read("birdnet_predictions_labelled.csv", usecols=["common_name", "folder"])}
    val = root / "data" / "raw" / "validation_results.csv"
    b["val"] = pd.read_csv(val) if val.exists() else None
    b["species"] = _species_decisions(b)
    return b


def _species_reason(sp: str, t, firth_cut, val) -> str:
    n_wrong = int(t.n_wrong)
    if t.status == "supported_exploratory_fit":
        return f"Fitted cutoff inside the checked score range; {n_wrong} errors give a usable curve."
    if t.status == "pending_review_sparse_errors":
        wrong = [] if val is None else sorted(val.loc[(val.commonName == sp) & (val.outcome == 0), "confidence"])
        at = f", at score {_and([f'{s:.3f}' for s in wrong])}" if wrong else ""
        moves = f"; cutoff moves {t.conf_threshold:.3f} → {firth_cut:.3f} under Firth" if pd.notna(firth_cut) else ""
        return f"{n_wrong} error{_s(n_wrong)}{at}{moves}."
    if t.status == "unsupported_fit" and n_wrong == 0:
        return f"{int(t.n_correct)} of {int(t.n)} checks correct: one outcome class, so no score relationship can be fitted."
    if t.status == "unsupported_target_outside_validation_range":
        return (f"Fitted {t.target_p:g} cutoff ({t.conf_threshold:.3f}) lies above the highest checked score "
                f"({t.validation_score_max:.3f}).")
    return f"Model status: {t.status.replace('_', ' ')}."


def _species_decisions(b: dict) -> list[dict]:
    rows = []
    for sp, t in b["thr"].iterrows():
        key, label = BIRD_DECISIONS.get(t.status, ("info", t.status.replace("_", " ")))
        lab = b["labels"].loc[sp]
        firth_cut = b["firth"].at[sp, "firth_conf_threshold"] if sp in b["firth"].index else np.nan
        rows.append({"name": sp, "short": sp.split()[-1], "key": key, "label": label, "t": t, "firth": firth_cut,
                     "checked": int(b["metrics"].at[sp, "checked"]), "correct": int(b["metrics"].at[sp, "correct"]),
                     "preds": int(lab.predictions), "cands": int(lab.fitted_candidates), "obs": int(lab.observations),
                     "reason": _species_reason(sp, t, firth_cut, b["val"])})
    rank = {"good": 0, "warning": 1, "info": 2}
    return sorted(rows, key=lambda r: (rank[r["key"]], -r["preds"]))


def bird_numbers(b: dict) -> dict:
    sp, thr, links = b["species"], b["thr"], b["links"]
    target = float(thr.target_p.iloc[0])
    return {
        "n_pred": int(b["labels"].predictions.sum()), "n_obs": int(b["labels"].observations.sum()),
        "n_checked": int(b["metrics"].checked.sum()), "n_links": len(links),
        "unique_links": int((links.candidate_matches == 1).sum()), "n_recorders": int(b["pred"].folder.nunique()),
        "released": [s for s in sp if s["key"] == "good"], "held": [s for s in sp if s["key"] == "warning"],
        "other": [s for s in sp if s["key"] == "info"], "target": target,
        "sensitivity": float(thr.sensitivity_assumed.iloc[0]), "model": thr.model_version.iloc[0],
        "policy": thr.policy_version.iloc[0], "recall_known": bool(b["metrics"].recall.notna().any()),
        "birdnet": None if b["val"] is None else b["val"].vBirdNET.iloc[0],
        # Zero errors in n checks gives a one-sided 95% lower bound of 0.05**(1/n).
        "checks_for_target": math.ceil(math.log(0.05) / math.log(target)),
    }


def load_vegetation(root: Path) -> dict | None:
    out = root / "outputs"
    if not all((out / f).exists() for f in VEG_FILES):
        return None
    read = lambda f: pd.read_csv(out / f)
    v = {"plots": read("veg_plot_summary.csv"), "flags": read("veg_qa_flags.csv"),
         "effort": read("veg_sampling_effort.csv"), "geo": read("vegetation_transect_geometry.csv"),
         "coverage": read("vegetation_plot_coverage.csv"), "patterns": read("vegetation_project_patterns.csv"),
         "rules": read("vegetation_rule_catalogue.csv"),
         "summary": pd.read_csv(out / "veg_survey_summary.csv", index_col=0)["value"],
         "qa": json.loads((out / "vegetation_qa_parameters.json").read_text(encoding="utf-8"))}
    cent = root / "data" / "raw" / "centroids.csv"
    v["centroids"] = pd.read_csv(cent) if cent.exists() else None
    v.update(_veg_numbers(v))
    return v


def _veg_numbers(v: dict) -> dict:
    plots, cov, geo, qa, s = v["plots"], v["coverage"], v["geo"], v["qa"], v["summary"]
    acc = plots[plots.include_in_analysis.astype(bool)]
    prio = transect_priorities(geo, plots, v["flags"], qa)
    queue = (prio.merge(geo, on="plot_name", how="left")
             .merge(acc[["plot_name", "flagged_quadrats", "actual_quadrats", "median_distance_m",
                         "provisional_richness", "error", "warning", "info"]], on="plot_name", how="left")
             .merge(v["effort"][["plot_name", "expected_new_taxa_in_final_up_to_5_quadrats"]], on="plot_name", how="left"))
    queue["rank"] = queue.priority.map(PRIORITY_ORDER.index)
    queue = queue.sort_values(["rank", "flagged_quadrats"], ascending=[True, False])
    primary = cov[cov.sample_status == "primary"]
    viable = geo[geo.is_viable == "yes"].dropna(subset=["bearing_deg"])
    bearing = float(viable.bearing_deg.median())
    n = lambda key: int(s[key])
    return {
        "queue": queue, "counts": prio.priority.value_counts().to_dict(),
        "critical": queue[queue.priority == "critical"].plot_name.tolist(),
        "n_sub": n("all_submissions"), "n_analysed": n("analysis_submissions"), "n_rejected": n("rejected_submissions"),
        "n_quadrats": n("analysis_quadrat_rows"), "n_herbs": n("analysis_quadrats_with_herbs"),
        "off_line": int(acc.flagged_quadrats.sum()),
        "errors": n("flags_errors"), "warnings": n("flags_warnings"), "infos": n("flags_info"),
        "n_primary": len(primary), "primary_surveyed": int((primary.n_submissions > 0).sum()),
        "never_registered": primary[primary.vegplot_linked.ne("yes")].plot_name.tolist(),
        "nonviable": cov[cov.is_viable == "no"].plot_name.tolist(),
        "backups_used": cov[(cov.sample_status == "backup") & (cov.n_submissions > 0)].plot_name.tolist(),
        "complete": bool(acc.actual_quadrats.eq(qa["expected_quadrats"]).all()),
        "n_viable": len(viable), "rotated": int((viable.ns_deviation_deg > qa["bearing_tolerance_deg"]).sum()),
        "bearing": bearing, "direction": "east–west" if 45 <= bearing % 180 <= 135 else "north–south",
        "continuing": int(v["effort"].effort_interpretation.str.startswith("continued").sum()),
        "rule_version": v["rules"].rule_version.iloc[0], "project": s["project"], "area": s["area"],
    }


# ---------------------------------------------------------------------------- pages
def overview_page(b: dict | None, v: dict | None) -> str:
    bird_card = notice("01", "bird")
    if b:
        nb = bird_numbers(b)
        items = [("good", f'{s["short"]} released: cutoff {s["t"].conf_threshold:.3f}, {s["obs"]:,} observations.') for s in nb["released"]]
        items += [("warning", f'{s["short"]} held: {s["cands"]:,} fitted candidates rest on {int(s["t"].n_wrong)} '
                              f'expert error{_s(int(s["t"].n_wrong))}.') for s in nb["held"]]
        if nb["other"]:
            items.append((("info", "–"), f'{_and([s["short"] for s in nb["other"]])}: the requested model cannot support a '
                                          f'{nb["target"]:g} cutoff.'))
        bird_card = (
            f'<div class="q">Which BirdNET predictions count as observations at fitted P(correct) ≥ {nb["target"]:g}?</div>'
            f'<div class="kpis mini">{kpi(f"{nb['n_pred']:,}", "predictions")}{kpi(f"{nb['n_obs']:,}", "observations")}'
            f'{kpi(of(len(nb["released"]), len(b["species"])), "species released")}</div>{findings(items)}'
            f'<div class="cs">{FUNNEL_KEY}</div>{funnel(b["species"])}'
            f'<div class="limits"><span><b>{nb["unique_links"]}/{nb["n_links"]}</b>checks link uniquely to a prediction</span>'
            f'<span><b>Recall</b>{"reported" if nb["recall_known"] else "unavailable"}</span>'
            f'<span><b>{nb["target"]:.0%}</b>fitted, not certified</span></div>'
            f'{source("bird_label_summary.csv", "bird_thresholds.csv", "bird_validation_link_audit.csv")}'
            f'<div class="actions"><a class="btn primary" href="birds.html">Open birds page →</a></div>')
    veg_card = notice("02", "vegetation")
    if v:
        items = [("warning", f'{_all_of(v["rotated"], v["n_viable"]).capitalize()} transects run '
                             f'roughly {v["direction"]} (median {v["bearing"]:.0f}°), not north–south.')]
        if v["critical"]:
            items.append(("critical", f'Plots {_and([_short(p) for p in v["critical"]])}: '
                                      f'{priority_rules(v["qa"])["critical"]}.'))
        if v["never_registered"]:
            items.append(("warning", f'{len(v["never_registered"])} primary plots ({_plot_range(v["never_registered"])}) '
                                     f"were never registered."))
        veg_card = (
            '<div class="q">Are the herbaceous survey records fit for analysis, and what must be reviewed first?</div>'
            f'<div class="kpis mini">{kpi(of(v["n_analysed"], v["n_sub"]), "submissions analysed")}'
            f'{kpi(of(v["primary_surveyed"], v["n_primary"]), "primaries surveyed")}'
            f'{kpi(f"{v['errors']} · {v['warnings']}", "errors · warnings")}</div>{findings(items)}'
            f'<div class="mapwrap">{_veg_map(v)}</div>{map_legend(v["counts"], len(v["never_registered"]), len(v["nonviable"]))}'
            f'{source("vegetation_transect_geometry.csv", "veg_plot_summary.csv", "vegetation_plot_coverage.csv")}'
            f'<div class="actions"><a class="btn primary" href="vegetation.html">Open vegetation page →</a>'
            f'<a class="btn ghost" href="../transect_map.html">Interactive map</a></div>')

    questions = []
    if b:
        questions += [("Birds", f'Was the {nb["n_links"]}-clip validation sample drawn from this prediction file? '
                                f'Only {nb["unique_links"]} clips link uniquely.'),
                      ("Birds", "How should species with no expert errors, or very few, be handled?"),
                      ("Birds", f'Which BirdNET sensitivity setting produced these scores? {nb["sensitivity"]:.1f} is assumed.')]
    if v:
        questions.append(("Vegetation", f'Are transects laid {v["direction"]} in practice, or were endpoints captured wrongly?'))
        calc = v["patterns"][v["patterns"].finding.str.startswith("Stored calculation")]
        if len(calc):
            questions.append(("Vegetation", f"Why does the stored 'quadrats with species' count differ from the form's formula "
                                            f"in {int(calc.affected_records.iloc[0])} of {int(calc.denominator.iloc[0])} submissions?"))
        if v["nonviable"] and v["never_registered"]:
            backup = f'backup Plot {_plot_range(v["backups_used"])}' if v["backups_used"] else "a backup plot"
            questions.append(("Vegetation", f'Did {backup} replace non-viable Plot {_plot_range(v["nonviable"])}, and why were '
                                            f'primaries {_plot_range(v["never_registered"])} not registered?'))
    q_html = "".join(f'<li><span class="tag tag-{a.lower()}">{a}</span>{esc(q)}</li>' for a, q in questions)
    versions = ([nb["model"], nb["policy"]] if b else []) + ([v["rule_version"]] if v else [])
    rules = ['<li><b>Status is never colour alone.</b> Every coloured mark carries an icon and a label.</li>',
             '<li><b>Flags request review.</b> No field value, name or coordinate is corrected.</li>']
    if b:
        rules += [f'<li><b>A fitted {nb["target"]:.0%} is not certified precision.</b> No species reaches '
                  f'{nb["target"]:.0%} on a strict lower bound; that would need about {nb["checks_for_target"]} error-free checks.</li>',
                  '<li><b>Recall is unavailable.</b> Calls BirdNET missed were never annotated.</li>' if not nb["recall_known"] else ""]
    rules.append('<li><b>Every panel names its source file</b> in <code>outputs/</code>, so each number can be traced.</li>')
    return f"""
<div class="eyebrow">Results overview</div>
<h1>What the data support, and what needs review</h1>
<p class="sub">Two independent analyses. Each page answers one question in the same order: the answer, headline numbers,
the decision, the evidence, then the records to review.</p>
<div class="two">
  <section class="card ov"><div class="ovh"><span class="dot" style="background:var(--blue)"></span>Birds · BirdNET</div>{bird_card}</section>
  <section class="card ov"><div class="ovh"><span class="dot" style="background:var(--good)"></span>Vegetation · herbaceous QA</div>{veg_card}</section>
</div>
<div class="two" style="margin-top:14px">
  {card("Questions for Natural State", "Decisions the data cannot settle on their own", f'<ol class="qs">{q_html}</ol>')}
  {card("How to read these pages", "Conventions used throughout",
        f'<ul class="rules">{"".join(rules)}</ul><div class="src">Versions: '
        + " · ".join(f"<code>{esc(x)}</code>" for x in versions) + '</div>'
        + '<div class="actions"><a class="btn ghost" href="files.html">All output files →</a></div>')}
</div>"""


def birds_page(b: dict | None) -> str:
    head = '<div class="eyebrow">Birds · BirdNET observations</div><h1>Which predictions become observations?</h1>'
    if not b:
        return head + notice("01", "bird")
    nb, sp = bird_numbers(b), b["species"]
    released = nb["released"]
    others = len(sp) - len(released)
    answer = (f'Only {_and([s["name"] for s in released])} is released ({nb["n_obs"]:,} observations).' if len(released) == 1
              else f'{len(released)} species are released ({nb["n_obs"]:,} observations).')
    answer += (f" The other {others} species stay <i>unconfirmed</i>, which means not confirmed, not absent." if others else "")
    held = nb["held"]
    kpis = "".join([
        kpi(f'{nb["n_pred"]:,}', "BirdNET predictions", f'{len(sp)} species · {nb["n_recorders"]} recorders'),
        kpi(f'{nb["n_checked"]:,}', "expert-checked clips", f'BirdNET {esc(nb["birdnet"])}' if nb["birdnet"] else ""),
        kpi(f'{nb["n_obs"]:,}', "observations released", f'{nb["n_obs"] / nb["n_pred"]:.1%} of predictions'),
        kpi(f'{sum(s["cands"] for s in held):,}', f'{_and([s["short"] for s in held]) or "Held"} candidates held', "fitted, not released"),
        kpi(of(len(released), len(sp)), "species released", _and([s["short"] for s in released]) + " only" if released else ""),
    ])
    cards = "".join(
        f'<div class="sc"><div class="scn">{esc(s["name"])}</div>{chip(s["key"], s["label"], "–" if s["key"] == "info" else None)}'
        f'<div class="scg"><div><b>{of(s["correct"], s["checked"])}</b><span>checks correct</span></div>'
        f'<div><b>{_num(s["t"].conf_threshold)}</b><span>fitted cutoff</span></div>'
        f'<div><b>{s["obs"]:,}</b><span>observations</span></div></div><div class="scw">{esc(s["reason"])}</div></div>'
        for s in sp)
    calib = "".join(
        f'<div class="cm"><div class="cmh">{esc(s["name"])}</div>{calibration_svg(s, b["val"], nb["target"])}<div class="cap">'
        f'<span><span class="ln-solid" style="--c:{COLOUR[s["key"]]}"></span>GLM <b>{_num(s["t"].conf_threshold)}</b></span>'
        f'<span><span class="ln-dot"></span>Firth <b>{_num(s["firth"], none="none")}</b></span></div></div>' for s in sp)
    ev_rows = []
    for s in sp:
        name, e, m = s["name"], b["evidence"].loc[s["name"]], b["metrics"].loc[s["name"]]
        at = f"{int(e.correct)}/{int(e.checked)}" if e.checked else "0 checked"
        ev_rows.append(
            f'<tr><td><b>{esc(name)}</b></td>'
            + td(f'{_pct(m.sample_precision)}<span class="ci">{m.wilson_95_lower:.0%}–{m.wilson_95_upper:.0%}</span>', m.sample_precision)
            + td(_pct(b["binw"].at[name, "weighted_estimate_covered_bins"]), b["binw"].at[name, "weighted_estimate_covered_bins"])
            + td(_num(s["t"].conf_threshold), s["t"].conf_threshold) + td(_num(s["firth"], none="none"), s["firth"])
            + td(at, e.checked) + td(_pct(e.one_sided_95_lower), e.one_sided_95_lower)
            + td(chip(s["key"], s["label"], "–" if s["key"] == "info" else None), s["label"], numeric=False) + "</tr>")
    table = sortable_table([("Species", False), ("Checked precision (Wilson 95%)", True), ("Population-weighted", True),
                            ("GLM cutoff", True), ("Firth cutoff", True), ("Checks at cutoff", True), ("Lower bound", True),
                            ("Decision", False)], ev_rows)
    best = b["evidence"].one_sided_95_lower.max()
    bound_note = (f"None reaches {nb['target']:.0%}." if best < nb["target"] else "")
    limits = (f'<div><b>{of(nb["unique_links"], nb["n_links"])}</b><span>validated clips link uniquely to a prediction; '
              f'no expert overrides applied</span></div>'
              f'<div><b>Recall</b><span>{"reported in bird_validation_metrics.csv" if nb["recall_known"] else "unavailable: missed calls were never annotated"}</span></div>'
              f'<div><b>Sensitivity {nb["sensitivity"]:.1f}</b><span>assumed; confirm from BirdNET run settings</span></div>'
              f'<div><b>Same-sample fit</b><span>no independent test set; revalidate before production</span></div>')
    return f"""{head}
<p class="sub">Per species: logistic fit of expert outcome on logit(score); a prediction is an observation when fitted
P(correct) ≥ {nb["target"]:g} and the species passes the support policy.</p>
<div class="answer"><b>Answer.</b>{answer}</div>
<div class="kpis">{kpis}</div>
<div class="stack">
{card("Decision per species", "Why each species is released, held or unsupported", f'<div class="scs">{cards}</div>',
      ("bird_thresholds.csv", "bird_label_summary.csv", "bird_validation_metrics.csv"))}
{card("Calibration curves", f'Expert checks ({swatch("var(--blue)")}correct '
      f'{swatch("var(--critical)")}wrong), fitted P(correct) (line), {nb["target"]:g} target '
      f'(dashed), GLM cutoff (solid) and Firth cutoff (dotted). Hover a point for its score.', f'<div class="cms">{calib}</div>',
      ("validation_results.csv (data/raw)", "bird_thresholds.csv", "bird_firth_sensitivity.csv"))}
{card("Evidence behind each decision", "Checked-sample figures; thresholds were fitted on the same clips. Click a heading to sort.",
      table + f'<div class="note">Lower bound = one-sided exact 95% bound on precision among checked clips at or above '
              f'the cutoff. {bound_note}</div>',
      ("bird_checked_cutoff_evidence.csv", "bird_bin_weighted_precision.csv", "bird_firth_sensitivity.csv"))}
<div class="two">
  {card("Predictions → candidates → observations", FUNNEL_KEY, funnel(sp)
        + (f'<div class="note">{_and([s["short"] for s in held])} candidates are kept in <code>candidate_observation</code> '
           f'for review; the final <code>observation</code> is <i>unconfirmed</i>.</div>' if held else ""),
        ("bird_label_summary.csv",))}
  {card("Limits to keep in view", "What these results cannot show", f'<div class="lims">{limits}</div>',
        ("bird_validation_link_audit.csv", "bird_thresholds.csv"))}
</div>
</div>"""


def vegetation_page(v: dict | None) -> str:
    head = '<div class="eyebrow">Vegetation · herbaceous QA/QC</div><h1>Is the herbaceous survey fit for analysis?</h1>'
    if not v:
        return head + notice("02", "vegetation")
    qa = v["qa"]
    n_crit = v["counts"].get("critical", 0)
    complete = (f'Every analysed submission has its {qa["expected_quadrats"]} quadrats' if v["complete"]
                else f'Not every analysed submission has {qa["expected_quadrats"]} quadrats')
    answer = (f'{"Yes, with review" if v["complete"] else "Partly"}. {complete} and {v["errors"]} record '
              f'error{_s(v["errors"])}, but the spatial layout needs checking: {n_crit} plot{_s(n_crit)} '
              f'{"is" if n_crit == 1 else "are"} critical and {_all_of(v["rotated"], v["n_viable"])} transects run roughly '
              f'{v["direction"]}.')
    kpis = "".join([
        kpi(of(v["n_analysed"], v["n_sub"]), "submissions analysed", f'{v["n_rejected"]} rejected kept for QA only'),
        kpi(of(v["primary_surveyed"], v["n_primary"]), "primary plots surveyed",
            f'{len(v["never_registered"])} never registered · {len(v["nonviable"])} non-viable'),
        kpi(f'{v["n_quadrats"]:,}', "quadrats analysed", f'{v["n_herbs"]:,} with herbs'),
        kpi(of(v["off_line"], v["n_quadrats"]), "quadrats off the line", "accepted submissions"),
        kpi(" ".join(f'{swatch(COLOUR[k])}{n}' for k, n in
                     [("critical", v["errors"]), ("warning", v["warnings"]), ("info", v["infos"])]), "QA flags", "error · warning · info"),
    ])
    pat = [(SEVERITY_STATUS.get(p.severity, "info"), p.finding, p.interpretation, p.affected_records, p.denominator)
           for p in v["patterns"].itertuples()]
    if v["never_registered"]:
        pat.append(("warning", f'Primary plots never registered ({_plot_range(v["never_registered"])})',
                    "Spatial coverage gap; no replacement crosswalk supplied.", len(v["never_registered"]), v["n_primary"]))
    find_html = "".join(f'<div class="fd">{ic(k)}<div><div class="ft">{esc(f)}</div><div class="fs">{esc(i)}</div></div>'
                        f'<div class="fn">{of(int(a), int(d))}</div></div>' for k, f, i, a, d in pat)
    rules = priority_rules(qa)
    prio_box = ('<div class="prio"><div class="prioh">How review priority is assigned</div>'
                + "".join(f'<div class="pr">{ic(k)}<b>{STATUS[k]["label"]}</b><span>{esc(rules[k])}</span></div>' for k in PRIORITY_ORDER)
                + f'<p>Off the line = farther than the {qa["belt_half_width_m"]:g} m belt half-width + the quadrat\'s GPS accuracy '
                  f'+ a {qa["gps_accuracy_max_m"]:g} m allowance. Orientation is reported once, above, not per plot.</p></div>')
    q = v["queue"]
    rows = [f'<tr data-priority="{r.priority}"><td data-v="{int(_short(r.plot_name))}"><b>Plot {_short(r.plot_name)}</b></td>'
            + td(chip(r.priority, STATUS[r.priority]["label"]), r.rank, numeric=False)
            + td("—" if pd.isna(r.flagged_quadrats) else f"{int(r.flagged_quadrats)}/{int(r.actual_quadrats)}", r.flagged_quadrats)
            + td(_num(r.median_distance_m, ".1f") + " m", r.median_distance_m) + td(f"{r.length_m:.0f} m", r.length_m)
            + td(f"{r.bearing_deg:.0f}°", r.bearing_deg) + td(f"{r.midpoint_offset_m:.0f} m", r.midpoint_offset_m)
            + td(_num(r.provisional_richness, ".0f"), r.provisional_richness)
            + td(_num(r.expected_new_taxa_in_final_up_to_5_quadrats, "+.1f"), r.expected_new_taxa_in_final_up_to_5_quadrats)
            + td(" ".join(f'{swatch(COLOUR[k])}{0 if pd.isna(n) else int(n)}'
                          for k, n in [("critical", r.error), ("warning", r.warning), ("info", r.info)]),
                 (r.error or 0) * 1000 + (r.warning or 0)) + "</tr>"
            for r in q.itertuples()]
    options = "".join(f'<option value="{k}">{STATUS[k]["label"]} ({v["counts"].get(k, 0)})</option>' for k in PRIORITY_ORDER)
    queue = (f'<div class="toolbar"><label>Review priority <select id="priority-filter"><option value="">All ({len(q)})</option>'
             f'{options}</select></label><span><b id="queue-count">{len(q)}</b> of {len(q)} plots shown · click a heading to sort'
             f'</span></div>' + sortable_table(
                 [("Plot", False), ("Priority", False), ("Off-line quadrats", True), ("Median distance", True),
                  ("Length", True), ("Bearing", True), ("Midpoint shift", True), ("Richness", True), ("Last-5 gain", True),
                  ("Flags E · W · I", True)], rows, "queue"))
    n_eff = len(v["effort"])
    complete_note = (f'All {v["n_analysed"]} analysed submissions completed {qa["expected_quadrats"]} quadrats. ' if v["complete"] else "")
    return f"""{head}
<p class="sub">{esc(v["project"])} · area {esc(v["area"])}. Flags request review; no field value is corrected.</p>
<div class="answer"><b>Answer.</b>{answer}</div>
<div class="kpis">{kpis}</div>
<div class="stack">
<div class="grid">
  {card("Where to look first", "Registered plots coloured by spatial review priority; planned locations without a survey shown separately. Hover a mark for detail.",
        f'<div class="mapwrap">{_veg_map(v)}</div>{map_legend(v["counts"], len(v["never_registered"]), len(v["nonviable"]))}'
        '<div class="actions"><a class="btn primary" href="../transect_map.html">Open interactive transect map →</a></div>',
        ("vegetation_transect_geometry.csv", "veg_plot_summary.csv", "vegetation_plot_coverage.csv", "centroids.csv (data/raw)"))}
  {card("Project-level findings", "Patterns that affect many records, reported once", find_html + prio_box,
        ("vegetation_project_patterns.csv", "vegetation_plot_coverage.csv", "vegetation_qa_parameters.json"))}
</div>
<div class="two">
  {card("QA flags by rule", f'{len(v["flags"]):,} flag rows · ' + " ".join(
        f'{swatch(COLOUR[k])}{w}' for k, w in [("critical", "error"), ("warning", "warning"), ("info", "info")]),
        rule_bars(v["flags"], v["rules"]), ("veg_qa_flags.csv", "vegetation_rule_catalogue.csv"))}
  {card("Sampling effort", f'{v["continuing"]} of {n_eff} plots still adding taxa at quadrat {qa["expected_quadrats"]} '
        f'({swatch("var(--blue)")}blue); {n_eff - v["continuing"]} levelling off '
        f'({swatch("var(--info)")}grey)', effort_svg(v["effort"])
        + f'<div class="note">{complete_note}Protocol completion is not proof of ecological adequacy.</div>',
        ("veg_sampling_effort.csv",))}
</div>
{card("Plot review queue", "Plots with a registered transect, highest priority first", queue,
      ("veg_plot_summary.csv", "vegetation_transect_geometry.csv", "veg_sampling_effort.csv", "veg_qa_flags.csv"))}
</div>"""


def _file_info(path: Path) -> tuple[str, dict | None]:
    """'rows · cols · size' text and an embedded preview (None when the file opens on its own)."""
    size = _size(path.stat().st_size)
    if path.suffix == ".csv":
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        rows = df.head(PREVIEW_ROWS).map(lambda x: x[:PREVIEW_CELL_CHARS]).values.tolist()
        note = (f"First {len(rows)} of {len(df):,} rows" if len(df) > len(rows)
                else f"All {len(df)} rows" if len(df) else "Header only: this table has no rows")
        header = ["" if c.startswith("Unnamed: ") else c for c in df.columns]
        return f"{len(df):,} rows · {df.shape[1]} cols · {size}", {"kind": "table", "header": header, "rows": rows,
                                                                    "total": len(df), "note": note}
    if path.suffix in (".json", ".geojson"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("type") == "FeatureCollection":
            feats = data.get("features", [])
            text = f"{len(feats):,} features. First feature:\n\n" + (json.dumps(feats[0], indent=2) if feats else "(none)")
            return f"{len(feats):,} features · {size}", {"kind": "text", "text": text, "note": "First feature only"}
        text = json.dumps(data, indent=2)
        cut = len(text) > PREVIEW_JSON_CHARS
        meta = f"{len(data)} fields" if isinstance(data, dict) else f"{len(data):,} items"
        return f"{meta} · {size}", {"kind": "text", "text": text[:PREVIEW_JSON_CHARS] + ("\n…" if cut else ""),
                                    "note": f"First {PREVIEW_JSON_CHARS // 1000} KB" if cut else ""}
    return size, None


def files_page(out: Path) -> tuple[str, dict]:
    groups: dict[str, list[str]] = {k: [] for k in FILE_GROUPS}
    previews: dict[str, dict] = {}
    order = {name: i for i, name in enumerate(FILE_DESCRIPTIONS)}
    paths = sorted((p for p in out.rglob("*") if p.is_file() and "dashboard" not in p.relative_to(out).parts
                    and not p.name.startswith(".") and p.relative_to(out).as_posix() != "index.html"),
                   key=lambda p: (order.get(p.relative_to(out).as_posix(), len(order)), p.relative_to(out).as_posix()))
    for p in paths:
        rel = p.relative_to(out).as_posix()
        href = "../" + quote(rel)
        group, desc = FILE_DESCRIPTIONS.get(rel, ("figures" if rel.startswith("figures/") and p.suffix == ".png" else "other", ""))
        search = esc(f"{rel} {desc}".lower())
        if group == "figures":
            title = desc or p.stem.split("_", 1)[-1].replace("_", " ").capitalize()
            groups[group].append(
                f'<figure class="fig" data-search="{search}"><a href="{href}" target="_blank" rel="noopener" '
                f'title="Open full size"><img src="{href}" alt="{esc(title)}" loading="lazy"></a><figcaption class="fcap">'
                f'<span class="fcode">{esc(p.stem.split("_", 1)[0])}</span>{esc(title)}'
                f'<a class="btn ghost" href="{href}" download>Download</a></figcaption></figure>')
            continue
        meta, preview = _file_info(p)
        kind = {".csv": "CSV", ".json": "JSON", ".geojson": "GEO", ".html": "HTML", ".png": "PNG"}.get(p.suffix, "FILE")
        if preview:
            previews[rel] = {**preview, "href": href}
            view = f'<button type="button" class="btn ghost" data-preview="{esc(rel)}">Preview</button>'
        else:
            view = f'<a class="btn ghost" href="{href}" target="_blank" rel="noopener">Open</a>'
        desc_html = (f'<div class="fdesc">{esc(desc)}</div>' if desc else '<div class="fdesc missing">No description yet</div>')
        groups[group].append(
            f'<li class="file" data-search="{search}"><span class="badge b-{kind.lower() if kind != "FILE" else "other"}">'
            f'{kind}</span><div class="fmain"><a class="fname" href="{href}">{esc(rel)}</a>{desc_html}</div>'
            f'<div class="fmeta">{esc(meta)}</div><div class="factions">{view}'
            f'<a class="btn ghost" href="{href}" download>Download</a></div></li>')
    sections = []
    for key, (title, sub) in FILE_GROUPS.items():
        if groups[key]:
            body = (f'<div class="figs">{"".join(groups[key])}</div>' if key == "figures"
                    else f'<ul class="files">{"".join(groups[key])}</ul>')
            sections.append(f'<section class="card group"><div class="gh"><h2>{title}</h2><span>{sub}</span></div>{body}</section>')
    data = json.dumps(previews, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = f"""<div class="head-row"><div><div class="eyebrow">Output files</div><h1>Every output, previewed and downloadable</h1>
<p class="sub" style="margin:0">Everything in <code>outputs/</code>, regenerated by notebooks 01 and 02. Previews are embedded,
so they work offline; downloads link to the real files.</p></div>
<label class="search"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
 stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
<input id="file-filter" type="search" placeholder="Filter files…" aria-label="Filter files by name or description"></label></div>
<div class="stack">{"".join(sections)}<p class="empty" id="no-match" hidden>No files match that filter.</p></div>
<dialog id="preview" aria-labelledby="preview-title"><div class="dh"><h2 id="preview-title"></h2><small></small>
<a class="btn ghost" download>Download</a><button type="button" class="btn ghost close">Close</button></div>
<div class="db"></div></dialog>
<script type="application/json" id="preview-data">{data}</script>"""
    return page, previews


# ---------------------------------------------------------------------------- shell and build
NAV = [("index.html", "Overview"), ("birds.html", "Birds"), ("vegetation.html", "Vegetation"), ("files.html", "Files")]
THEME_BOOT = ("<script>try{var t=localStorage.getItem('ns-theme');"
              "if(t==='light'||t==='dark')document.documentElement.dataset.theme=t}catch(e){}</script>")
SUN = ('<svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
       'aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2'
       'M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>')
MOON = ('<svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>')


def page(title: str, active: str, body: str) -> str:
    css = (ASSETS / "dashboard.css").read_text(encoding="utf-8")
    js = (ASSETS / "dashboard.js").read_text(encoding="utf-8")
    tabs = "".join(f'<a class="tab{" on" if href == active else ""}" href="{href}"'
                   f'{" aria-current=page" if href == active else ""}>{label}</a>' for href, label in NAV)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{THEME_BOOT}
<style>{css}</style>
</head>
<body>
<nav class="nav" aria-label="Dashboard pages"><span class="brand">Natural State results</span><div class="tabs">{tabs}</div>
<button type="button" id="theme-toggle" class="theme" aria-pressed="false" aria-label="Dark theme">{SUN}{MOON}<span class="tlabel">Light</span></button></nav>
<main class="wrap">{body}</main>
<script>{js}</script>
</body>
</html>
"""


# outputs/index.html: lets `python -m http.server --directory outputs` open the dashboard at "/".
# file:// shows a folder listing for "dashboard/", so name the page explicitly there.
REDIRECT = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Natural State results</title>
<meta http-equiv="refresh" content="0; url=dashboard/index.html">
<script>location.replace(location.protocol === 'file:' ? 'dashboard/index.html' : 'dashboard/');</script>
</head>
<body><p><a href="dashboard/index.html">Open the results dashboard</a></p></body>
</html>
"""


def build_dashboard(project_root: Path) -> list[Path]:
    """Write the four dashboard pages into <project_root>/outputs/dashboard and return their paths.

    Also writes outputs/index.html, a redirect to the dashboard, so serving outputs/ opens it at "/".
    """
    root = Path(project_root)
    out = root / "outputs"
    target = out / "dashboard"
    target.mkdir(parents=True, exist_ok=True)
    birds, veg = load_birds(root), load_vegetation(root)
    files_body, _ = files_page(out)
    pages = {"index.html": page("Results overview", "index.html", overview_page(birds, veg)),
             "birds.html": page("Birds results", "birds.html", birds_page(birds)),
             "vegetation.html": page("Vegetation QA results", "vegetation.html", vegetation_page(veg)),
             "files.html": page("Output files", "files.html", files_body)}
    written = []
    for name, content in pages.items():
        path = target / name
        path.write_text(content, encoding="utf-8")
        written.append(path)
    (out / "index.html").write_text(REDIRECT, encoding="utf-8")
    return written


if __name__ == "__main__":
    for p in build_dashboard(Path(__file__).resolve().parents[1]):
        print("wrote", p)
