"""Static four-page results dashboard built from the notebooks' exported outputs.

Writes outputs/dashboard/index.html (overview), birds.html, vegetation.html and files.html
(the last via src/dashboard_files.py). Every number is read at build time from outputs/ plus
three raw reference tables (validation clips, planned centroids, survey dates); nothing is
recomputed beyond counting and formatting. Pages are self-contained (inline CSS, JS and SVG)
and work offline, opened straight from disk. Images live in outputs/dashboard/assets/.

Run after the notebooks:  python -m src.dashboard
"""
from __future__ import annotations

import math
from pathlib import Path

import json
import numpy as np
import pandas as pd

from src.dashboard_charts import (COLOUR, FUNNEL_KEY, PRIORITY_ORDER, SEVERITY_STATUS, calibration_svg, effort_svg,
                                  esc, funnel, ic, map_legend, plot_map_svg, rule_bars, short_plot as _short, swatch)
from src.dashboard_files import files_page
from src.transect_map import STATUS, priority_rules, transect_priorities

ASSETS = Path(__file__).with_name("dashboard_assets")

# thresholds.status -> (status colour key, decision label, chip icon)
BIRD_DECISIONS = {
    "supported_exploratory_fit": ("good", "Released", "✓"),
    "pending_review_sparse_errors": ("warning", "Held for review", "!"),
    "unsupported_fit": ("info", "Not estimable", "–"),
    "unsupported_target_outside_validation_range": ("critical", "Out of range", "!"),
}
# Illustrations only (outputs/dashboard/assets/); not evidence of identification.
BIRD_IMAGES = {"Abyssinian Nightjar": "nightjar.png", "Three-banded Plover": "plover.png",
               "African Black-headed Oriole": "oriole.png", "Red-billed Firefinch": "firefinch.png"}
BIRD_FILES = ["bird_thresholds.csv", "bird_label_summary.csv", "bird_validation_metrics.csv",
              "bird_checked_cutoff_evidence.csv", "bird_bin_weighted_precision.csv",
              "bird_firth_sensitivity.csv", "bird_validation_link_audit.csv", "birdnet_predictions_labelled.csv"]
VEG_FILES = ["veg_plot_summary.csv", "veg_qa_flags.csv", "veg_sampling_effort.csv", "veg_survey_summary.csv",
             "vegetation_transect_geometry.csv", "vegetation_plot_coverage.csv", "vegetation_project_patterns.csv",
             "vegetation_rule_catalogue.csv", "vegetation_qa_parameters.json"]


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


def chip(status: str, label: str, icon: str | None = None) -> str:
    return f'<span class="chip c-{status}">{ic(status, icon)}{esc(label)}</span>'


def kpi(value: str, label: str, sub: str = "", green: bool = False) -> str:
    sub_html = f'<div class="ks">{sub}</div>' if sub else ""
    return f'<div class="kpi"><div class="kv{" green" if green else ""}">{value}</div><div class="kl">{label}</div>{sub_html}</div>'


def of(n, d) -> str:
    return f"{n:,}<small>/{d:,}</small>"


def source(*files: str) -> str:
    return '<div class="src">Source: ' + " · ".join(f"<code>{f}</code>" for f in files) + "</div>"


def card(title: str, sub: str, body: str, sources: tuple = (), pill: str = "", anchor: str = "", cls: str = "card") -> str:
    sub_html = f'<div class="cs">{sub}</div>' if sub else ""
    id_attr = f' id="{anchor}"' if anchor else ""
    return (f'<section class="{cls}"{id_attr}><div class="ch"><div><h2>{title}</h2>{sub_html}</div>{pill}</div>'
            f'{body}{source(*sources) if sources else ""}</section>')


def pill(text: str, tone: str = "") -> str:
    return f'<span class="pill {tone}">{esc(text)}</span>'


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


def hero(eyebrow: str, title: str, sub: str, aside: str = "") -> str:
    """Page header with the landscape banner (set as --hero-img on <body>)."""
    return (f'<section class="hero"><div class="hero-text"><div class="eyebrow">{eyebrow}</div><h1>{title}</h1>'
            f'<p class="sub">{sub}</p></div>{aside}</section>')


def survey_dates(root: Path) -> str:
    """'19–27 May 2026' from the raw survey start times, or '' when unavailable."""
    path = root / "data" / "raw" / "herbaceous_veg_survey.csv"
    try:
        t = pd.to_datetime(pd.read_csv(path, usecols=["survey_begin-start_time"])["survey_begin-start_time"].str[:10])
    except (OSError, ValueError, KeyError):
        return ""
    a, b = t.min(), t.max()
    if a.month == b.month and a.year == b.year:
        return f"{a.day}–{b.day} {b:%B %Y}" if a.day != b.day else f"{b.day} {b:%B %Y}"
    return f"{a.day} {a:%b} – {b.day} {b:%b %Y}"


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
        return "Every check was correct: one outcome class, so no score relationship can be fitted."
    if t.status == "unsupported_target_outside_validation_range":
        return (f"Fitted {t.target_p:g} cutoff ({t.conf_threshold:.3f}) lies above the highest checked score "
                f"({t.validation_score_max:.3f}).")
    return f"Model status: {t.status.replace('_', ' ')}."


def _species_decisions(b: dict) -> list[dict]:
    rows = []
    for sp, t in b["thr"].iterrows():
        key, label, icon = BIRD_DECISIONS.get(t.status, ("info", t.status.replace("_", " "), "–"))
        lab = b["labels"].loc[sp]
        firth_cut = b["firth"].at[sp, "firth_conf_threshold"] if sp in b["firth"].index else np.nan
        rows.append({"name": sp, "short": sp.split()[-1], "key": key, "label": label, "icon": icon, "t": t, "firth": firth_cut,
                     "checked": int(b["metrics"].at[sp, "checked"]), "correct": int(b["metrics"].at[sp, "correct"]),
                     "preds": int(lab.predictions), "cands": int(lab.fitted_candidates), "obs": int(lab.observations),
                     "reason": _species_reason(sp, t, firth_cut, b["val"])})
    rank = {"good": 0, "warning": 1, "info": 2, "critical": 3}
    return sorted(rows, key=lambda r: (rank[r["key"]], -r["preds"]))


def bird_numbers(b: dict) -> dict:
    sp, thr, links = b["species"], b["thr"], b["links"]
    target = float(thr.target_p.iloc[0])
    return {
        "n_pred": int(b["labels"].predictions.sum()), "n_obs": int(b["labels"].observations.sum()),
        "n_checked": int(b["metrics"].checked.sum()), "n_links": len(links),
        "unique_links": int((links.candidate_matches == 1).sum()), "n_recorders": int(b["pred"].folder.nunique()),
        "released": [s for s in sp if s["key"] == "good"], "held": [s for s in sp if s["key"] == "warning"],
        "other": [s for s in sp if s["key"] in ("info", "critical")], "target": target,
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
def _bird_findings(nb: dict) -> list[tuple]:
    items = [("good", f'<b>{esc(s["name"])}:</b> released at cutoff {s["t"].conf_threshold:.3f} ({s["obs"]:,} observations).')
             for s in nb["released"]]
    items += [("warning", f'<b>{esc(s["name"])}:</b> {s["cands"]:,} fitted candidates held for expert review '
                          f'({int(s["t"].n_wrong)} expert error{_s(int(s["t"].n_wrong))}).') for s in nb["held"]]
    if nb["other"]:
        items.append((("info", "–"), f'<b>{_and([s["short"] for s in nb["other"]])}:</b> the requested model cannot '
                                     f'support a {nb["target"]:g} cutoff.'))
    return items


def _veg_findings(v: dict) -> list[tuple]:
    qa = v["qa"]
    items = []
    if v["complete"]:
        items.append(("good", f'All {v["n_analysed"]} analysed submissions record {qa["expected_quadrats"]} quadrats; '
                              f'{"only " if v["errors"] == 1 else ""}{v["errors"]} record error{_s(v["errors"])}.'))
    if v["critical"]:
        items.append((("critical", "!"), f'<b>Plots {_and([_short(p) for p in v["critical"]])}:</b> '
                                         f'{priority_rules(qa)["critical"]}.'))
    tail = (f'; {len(v["never_registered"])} primaries ({_plot_range(v["never_registered"])}) lack registration'
            if v["never_registered"] else "")
    items.append(("warning", f'{_all_of(v["rotated"], v["n_viable"]).capitalize()} transects trend {v["direction"]}'
                             f' (median {v["bearing"]:.0f}°){tail}.'))
    return items


def overview_page(b: dict | None, v: dict | None, dates: str) -> str:
    badge = ('<div class="hero-badge"><i class="ic s-good" aria-hidden="true">✓</i><div><b>Analysis complete</b>'
             'Results regenerated from notebooks 01–02</div></div>' if b and v else
             '<div class="hero-badge"><i class="ic s-warning" aria-hidden="true">!</i><div><b>Outputs missing</b>'
             'Run notebooks 01 and 02, then rebuild</div></div>')
    head = hero("Research &amp; monitoring / Results overview", "What the data support, and what needs review",
                "Two independent analyses. Clear decisions, supporting evidence, and a transparent queue of questions "
                "to resolve.", badge)
    diamond = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1 15 8 8 15 1 8z" fill="{c}"/></svg>'
    bird_body = notice("01", "bird")
    if b:
        nb = bird_numbers(b)
        bird_body = (
            f'<div class="q">Which predictions count as observations?</div>'
            f'<div class="cs">Decision at fitted P(correct) ≥ {nb["target"]:g}, subject to the evidence policy</div>'
            f'<div class="kpis mini">{kpi(f"{nb['n_pred']:,}", "predictions")}'
            f'{kpi(f"{nb['n_obs']:,}", "released observations", green=True)}'
            f'{kpi(of(len(nb["released"]), len(b["species"])), "species released")}</div>{findings(_bird_findings(nb))}'
            f'<div class="divider"></div><div class="cs" style="margin:0">{FUNNEL_KEY}</div>{funnel(b["species"])}'
            f'<div class="limits"><span><b>{nb["unique_links"]}/{nb["n_links"]}</b>checks link uniquely to a prediction</span>'
            f'<span><b>Recall</b>{"reported" if nb["recall_known"] else "unavailable"}</span>'
            f'<span><b>{nb["target"]:.0%}</b>fitted, not certified</span></div>'
            f'{source("bird_label_summary.csv", "bird_thresholds.csv", "bird_validation_link_audit.csv")}'
            f'<div class="actions"><a class="btn outline" href="birds.html">View BirdNET evidence →</a></div>')
    bird_pill = pill(f'{len(nb["released"])} species released') if b else ""
    veg_body = notice("02", "vegetation")
    if v:
        c = v["counts"]
        veg_body = (
            '<div class="q">Are survey records fit for analysis?</div>'
            f'<div class="cs">{"Yes, with targeted spatial and metadata review first" if v["complete"] else "Partly: see the gaps below"}</div>'
            f'<div class="kpis mini">{kpi(of(v["n_analysed"], v["n_sub"]), "submissions analysed")}'
            f'{kpi(of(v["primary_surveyed"], v["n_primary"]), "primary plots surveyed")}'
            f'{kpi(of(v["off_line"], v["n_quadrats"]), "quadrats off line")}</div>{findings(_veg_findings(v))}'
            f'<div class="divider"></div><div class="mini-h"><h3>Spatial review priorities</h3><span>'
            + " · ".join(f'{c.get(k, 0)} {k}' for k in ("critical", "serious", "warning")) + '</span></div>'
            f'<div class="mapwrap">{_veg_map(v)}</div>'
            f'{map_legend(v["counts"], len(v["never_registered"]), len(v["nonviable"]))}'
            f'{source("vegetation_transect_geometry.csv", "veg_plot_summary.csv", "vegetation_plot_coverage.csv")}'
            f'<div class="actions"><a class="btn outline" href="vegetation.html">View vegetation review →</a>'
            f'<a class="btn ghost" href="../transect_map.html">Interactive map</a></div>')
    veg_pill = pill("Review required", "amber") if v else ""

    questions = []
    if b:
        questions += [("Birds", f'Was the {nb["n_links"]}-clip validation sample drawn from this prediction file? '
                                f'Only {nb["unique_links"]} clips link uniquely.'),
                      ("Birds", "How should species with zero or very few expert errors be handled?"),
                      ("Birds", f'Which BirdNET sensitivity setting generated the scores? {nb["sensitivity"]:.1f} is assumed.')]
    if v:
        questions.append(("Vegetation", f'Were transects truly laid {v["direction"]}, or were endpoints captured incorrectly?'))
        calc = v["patterns"][v["patterns"].finding.str.startswith("Stored calculation")]
        if len(calc):
            questions.append(("Vegetation", f"Why does the stored species-quadrat count differ from the reconstruction in "
                                            f"{int(calc.affected_records.iloc[0])} of {int(calc.denominator.iloc[0])} submissions?"))
        if v["nonviable"] and v["never_registered"]:
            backup = f'backup Plot {_plot_range(v["backups_used"])}' if v["backups_used"] else "a backup plot"
            questions.append(("Vegetation", f'Did {backup} replace non-viable Plot {_plot_range(v["nonviable"])}, and why '
                                            f'were primaries {_plot_range(v["never_registered"])} never registered?'))
    q_html = "".join(f'<li><span><b>{a}</b> · {esc(q)}</span></li>' for a, q in questions)
    rules = []
    if b:
        rules.append(("info", f'Fitted {nb["target"]:.0%} ≠ certified precision',
                      f'No species reaches {nb["target"]:.0%} on a strict lower confidence bound; about '
                      f'{nb["checks_for_target"]} error-free expert checks would be needed.'))
        if not nb["recall_known"]:
            rules.append(("info", "Recall cannot be estimated here", "Bird calls missed by BirdNET were not separately annotated."))
    rules += [("warning", "Flags request review, not automatic correction",
               "Field values, names and GPS locations are preserved as supplied."),
              ("good", "Every number has an output source",
               "Each panel cites the file in outputs/ it was read from; status always pairs colour with an icon and label.")]
    rules_html = "".join(f'<li>{ic(k)}<div><b>{esc(t)}</b><span>{esc(d)}</span></div></li>' for k, t, d in rules)
    versions = ([nb["model"], nb["policy"]] if b else []) + ([v["rule_version"]] if v else [])
    return f"""{head}
<div class="two">
  <section class="card ov"><div class="ch"><div class="ovh">{diamond.format(c="var(--blue)")}Birds / BirdNET</div>{bird_pill}</div>{bird_body}</section>
  <section class="card ov"><div class="ch"><div class="ovh">{diamond.format(c="var(--green)")}Vegetation / Herbaceous QA</div>{veg_pill}</div>{veg_body}</section>
</div>
<div class="two" style="margin-top:16px">
  {card("Questions for Natural State", "These issues cannot be resolved from the supplied data alone",
        f'<ol class="qs">{q_html}</ol>', pill=pill(f"{len(questions)} open items", "grey"))}
  {card("How to interpret the results", "Methods and limitations applied consistently",
        f'<ul class="rules">{rules_html}</ul><div class="src">Versions: '
        + " · ".join(f"<code>{esc(x)}</code>" for x in versions) + '</div>'
        + '<div class="actions"><a class="btn ghost" href="files.html">All output files →</a></div>', pill=pill("Evidence first"))}
</div>"""


def birds_page(b: dict | None) -> str:
    if not b:
        return hero("Birds / BirdNET / Decision evidence", "Which predictions become observations?", "") + notice("01", "bird")
    nb, sp = bird_numbers(b), b["species"]
    released, held = nb["released"], nb["held"]
    others = len(sp) - len(released)
    head = hero("Birds / BirdNET / Decision evidence", "Which predictions become observations?",
                f"Per species: fit expert correctness against logit(score); release predictions only when fitted "
                f"P(correct) ≥ {nb['target']:g} and the evidence policy is met.",
                f'<span class="hero-pill">{pill(f"Model · {nb['model']}")}</span>')
    answer = (f'Only {_and([s["name"] for s in released])} is released ({nb["n_obs"]:,} observations).' if len(released) == 1
              else f'{len(released)} species are released ({nb["n_obs"]:,} observations).')
    answer += (f" The other {others} species remain <i>unconfirmed</i>, which does not mean absent." if others else "")
    kpis = "".join([
        kpi(f'{nb["n_pred"]:,}', "BirdNET predictions", f'{len(sp)} species · {nb["n_recorders"]} recorders'),
        kpi(f'{nb["n_checked"]:,}', "expert-checked clips", f'BirdNET {esc(nb["birdnet"])}' if nb["birdnet"] else ""),
        kpi(f'{nb["n_obs"]:,}', "observations released", f'{nb["n_obs"] / nb["n_pred"]:.1%} of predictions', green=True),
        kpi(f'{sum(s["cands"] for s in held):,}', f'{_and([s["short"] for s in held]) or "Held"} candidates held', "fitted, not released"),
        kpi(of(len(released), len(sp)), "species released", _and([s["short"] for s in released]) + " only" if released else ""),
    ])
    cards = []
    for s in sp:
        img = BIRD_IMAGES.get(s["name"])
        pic = (f'<img class="bird" src="assets/{img}" alt="Illustration of {esc(s["name"])}" loading="lazy">' if img
               else '<div class="bird-ph"></div>')
        cards.append(
            f'<article class="sc" style="--accent:{COLOUR[s["key"]]}"><div class="sc-top">{pic}<div>'
            f'<div class="scn">{esc(s["name"])}</div>{chip(s["key"], s["label"], s["icon"])}</div></div>'
            f'<div class="scw">{s["correct"]} / {s["checked"]} expert checks correct. {esc(s["reason"])}</div>'
            f'<div class="scg"><div><b>{_num(s["t"].conf_threshold)}</b><span>fitted cutoff</span></div>'
            f'<div><b>{s["obs"]:,}</b><span>observations</span></div></div></article>')
    calib = "".join(
        f'<div class="cm"><div class="cmh">{esc(s["name"])}</div>{calibration_svg(s, b["val"], nb["target"])}<div class="cap">'
        f'<span><span class="ln-solid" style="--c:{COLOUR[s["key"]]}"></span>GLM <b>{_num(s["t"].conf_threshold)}</b></span>'
        f'<span><span class="ln-dot"></span>Firth <b>{_num(s["firth"], none="none")}</b></span></div></div>' for s in sp)
    short_label = {"good": "Released", "warning": "Held", "info": "No fit", "critical": "Out of range"}
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
            + td(chip(s["key"], short_label[s["key"]], s["icon"]), s["label"], numeric=False) + "</tr>")
    table = sortable_table([("Species", False), ("Checked precision", True), ("Weighted", True),
                            ("GLM cutoff", True), ("Firth cutoff", True), ("Checks at cutoff", True), ("Lower bound", True),
                            ("Decision", False)], ev_rows)
    best = b["evidence"].one_sided_95_lower.max()
    bound_note = f"None reaches {nb['target']:.0%}." if best < nb["target"] else ""
    limits = [("warning", f'{nb["unique_links"]} / {nb["n_links"]} uniquely linked',
               f'{"Most" if nb["unique_links"] < nb["n_links"] / 2 else "Some"} validation clips do not join uniquely to a '
               f'prediction; no expert overrides were applied.'),
              (("info", "–"), "Recall is " + ("reported" if nb["recall_known"] else "unavailable"),
               "See bird_validation_metrics.csv." if nb["recall_known"] else "Missed calls were not annotated."),
              ("warning", f'Sensitivity {nb["sensitivity"]:.1f} is assumed', "Confirm the original BirdNET run settings."),
              ("info", "Same-sample model fit", "Thresholds were fitted on the checked clips; validate independently before production use.")]
    lim_html = "".join(f'<li>{ic(*k) if isinstance(k, tuple) else ic(k)}<div><b>{esc(t)}</b><span>{esc(d)}</span></div></li>'
                       for k, t, d in limits)
    return f"""{head}
<div class="answer">{ic("info")}<div><b>Decision:</b>{answer}</div></div>
<div class="kpis">{kpis}</div>
<div class="stack">
{card("Decision by species", "Release depends on fit, score range, and strength of expert evidence",
      f'<div class="scs">{"".join(cards)}</div><div class="note">Bird illustrations are for orientation only; they are not '
      f'evidence of identification.</div>', ("bird_thresholds.csv", "bird_label_summary.csv", "bird_validation_metrics.csv"),
      pill(f"{len(sp)} species reviewed", "grey"), "species")}
{card("Calibration curves", f'Points are expert checks ({swatch("#3b82f6")}correct {swatch("var(--critical)")}wrong) · line = '
      f'fitted P(correct) · dashed = {nb["target"]:g} target · coloured line = GLM cutoff · dotted = Firth cutoff. '
      f'Curves are drawn from the fitted coefficients; hover a point for its score.', f'<div class="cms">{calib}</div>',
      ("validation_results.csv (data/raw)", "bird_thresholds.csv", "bird_firth_sensitivity.csv"),
      pill(f'Target: fitted {nb["target"]:g}'), "calibration")}
<div class="grid ev" id="evidence">
  {card("Evidence behind each decision", "Checked-sample metrics; thresholds fitted on these same clips. Click a heading to sort.",
        table + f'<div class="note">Lower bound is a one-sided exact 95% confidence bound on checked precision at or above the '
                f'cutoff, not evidence of certified {nb["target"]:.0%}. {bound_note}</div>',
        ("bird_checked_cutoff_evidence.csv", "bird_bin_weighted_precision.csv", "bird_firth_sensitivity.csv"))}
  {card("Limits to keep in view", "Results should not be overstated", f'<ul class="lims">{lim_html}</ul>',
        ("bird_validation_link_audit.csv", "bird_thresholds.csv"))}
</div>
</div>"""


def vegetation_page(v: dict | None, dates: str) -> str:
    eyebrow = "Vegetation / Herbaceous QA / Spatial review"
    if not v:
        return hero(eyebrow, "Is the herbaceous survey fit for analysis?", "") + notice("02", "vegetation")
    qa = v["qa"]
    n_crit = v["counts"].get("critical", 0)
    head = hero(eyebrow, "Is the herbaceous survey fit for analysis?",
                f'{esc(v["project"])} · area {esc(v["area"])}{" · " + dates if dates else ""}. '
                f"Flags request review; no field value is corrected.",
                f'<span class="hero-pill">{pill(f"Rules · {v['rule_version']}")}</span>')
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
    flags_sub = f'{len(v["flags"]):,} flag rows · ' + " ".join(
        f'{swatch(COLOUR[k])}{w}' for k, w in [("critical", "error"), ("warning", "warning"), ("info", "info")])
    effort_sub = (f'{v["continuing"]} of {n_eff} plots still adding taxa at quadrat {qa["expected_quadrats"]} '
                  f'({swatch("var(--blue)")}blue); {n_eff - v["continuing"]} levelling off ({swatch("var(--info)")}grey)')
    return f"""{head}
<div class="answer" id="survey">{ic("info")}<div><b>Answer:</b>{answer}</div></div>
<div class="kpis">{kpis}</div>
<div class="stack">
<div class="grid">
  {card("Where to look first", "Registered plots coloured by spatial review priority; planned locations without a survey shown "
        "separately. Hover a mark for detail.",
        f'<div class="mapwrap">{_veg_map(v)}</div>{map_legend(v["counts"], len(v["never_registered"]), len(v["nonviable"]))}'
        '<div class="actions"><a class="btn outline" href="../transect_map.html">Open interactive transect map →</a></div>',
        ("vegetation_transect_geometry.csv", "veg_plot_summary.csv", "vegetation_plot_coverage.csv", "centroids.csv (data/raw)"),
        pill(f"{n_crit} critical", "grey"), "spatial")}
  {card("Project-level findings", "Patterns that affect many records, reported once", find_html + prio_box,
        ("vegetation_project_patterns.csv", "vegetation_plot_coverage.csv", "vegetation_qa_parameters.json"))}
</div>
<div class="two">
  {card("QA flags by rule", flags_sub, rule_bars(v["flags"], v["rules"]), ("veg_qa_flags.csv", "vegetation_rule_catalogue.csv"),
        anchor="flags")}
  {card("Sampling effort", effort_sub, effort_svg(v["effort"])
        + f'<div class="note">{complete_note}Protocol completion is not proof of ecological adequacy.</div>',
        ("veg_sampling_effort.csv",), anchor="effort")}
</div>
{card("Plot review queue", "Plots with a registered transect, highest priority first", queue,
      ("veg_plot_summary.csv", "vegetation_transect_geometry.csv", "veg_sampling_effort.csv", "veg_qa_flags.csv"), anchor="queue")}
</div>"""


def files_body(root: Path, target: Path) -> str:
    head = hero("Project / Outputs &amp; provenance", "Files and reproducibility",
                "A clear guide to the notebooks, source data, analysis tables, and figures used by the dashboard.")
    return head + files_page(root, target)


# ---------------------------------------------------------------------------- shell and build
TABS = [("index.html", "Overview"), ("birds.html", "Birds · BirdNET"), ("vegetation.html", "Vegetation · Herbaceous QA"),
        ("files.html", "Files")]
ICONS = {
    "grid": '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>',
    "diamond": '<path d="M12 3 21 12 12 21 3 12z"/>',
    "curve": '<path d="M3 18c5 0 5-12 9-12s4 12 9 12"/>',
    "check": '<path d="M9 11l3 3 8-8"/><path d="M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9"/>',
    "survey": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    "target": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>',
    "flag": '<path d="M5 21V4h11l-2 4 2 4H5"/>',
    "bars": '<path d="M5 20V10M10 20V4M15 20v-7M20 20V8"/>',
    "table": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 10v10"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    "book": '<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 19V5"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
}
# (group label, [(href, label, icon)]); the first link of each page is its "active" sidebar item.
SIDEBAR = [
    ("", [("index.html", "Overview", "grid")]),
    ("Birds · BirdNET", [("birds.html", "Species decisions", "diamond"), ("birds.html#calibration", "Calibration curves", "curve"),
                         ("birds.html#evidence", "Evidence &amp; validation", "check")]),
    ("Vegetation · QA", [("vegetation.html", "Survey overview", "survey"), ("vegetation.html#spatial", "Spatial review", "target"),
                         ("vegetation.html#flags", "QA flags", "flag"), ("vegetation.html#effort", "Sampling effort", "bars"),
                         ("vegetation.html#queue", "Plot review queue", "table")]),
    ("Project", [("files.html", "Files", "file"), ("files.html#methods", "Methods &amp; sources", "book"),
                 ("files.html#reproducibility", "Reproducibility", "refresh")]),
]
THEME_BOOT = ("<script>try{var t=localStorage.getItem('ns-theme');"
              "if(t==='light'||t==='dark')document.documentElement.dataset.theme=t}catch(e){}</script>")
SUN = ('<svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
       'aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2'
       'M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>')
MOON = ('<svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>')


def _sidebar(active: str, project: str, dates: str) -> str:
    parts = ['<a class="logo" href="index.html"><img src="assets/natural-state-full-logo.png" '
             'alt="Natural State: Restoring the Natural World"></a><nav class="side-nav" aria-label="Sections">']
    for label, links in SIDEBAR:
        if label:
            parts.append(f'<div class="sg">{label}</div>')
        for href, text, icon in links:
            on = href == active
            parts.append(f'<a class="sn{" on" if on else ""}" href="{href}"{" aria-current=page" if on else ""}>'
                         f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
                         f'stroke-linejoin="round" aria-hidden="true">{ICONS[icon]}</svg>{text}</a>')
    parts.append("</nav>")
    lines = "".join(f"<span>{esc(x)}</span>" for x in (dates, "Two independent analyses", "Notebook-driven outputs") if x)
    parts.append(f'<div class="side-card"><b>{esc(project)}</b>{lines}</div>')
    return '<aside class="side">' + "".join(parts) + "</aside>"


def page(title: str, active: str, body: str, project: str, dates: str) -> str:
    css = (ASSETS / "dashboard.css").read_text(encoding="utf-8")
    js = (ASSETS / "dashboard.js").read_text(encoding="utf-8")
    tabs = "".join(f'<a class="tab{" on" if href == active else ""}" href="{href}"'
                   f'{" aria-current=page" if href == active else ""}>{label}</a>' for href, label in TABS)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="icon" href="assets/natural-state-mark.png">
{THEME_BOOT}
<style>{css}</style>
</head>
<body style="--hero-img:url('assets/scenery.png');--side-img:url('assets/savanna_sidebar.png')">
<div class="app">
{_sidebar(active, project, dates)}
<div class="main">
<header class="topbar"><a class="top-mark" href="index.html"><img src="assets/natural-state-mark.png" alt="Natural State"></a>
<nav class="tabs" aria-label="Dashboard pages">{tabs}</nav>
<span class="crumb">{esc(project)} / Take-home analysis</span>
<button type="button" id="theme-toggle" class="theme" aria-pressed="false" aria-label="Dark theme">{SUN}{MOON}<span class="tlabel">Light</span></button></header>
<main class="wrap">{body}</main>
<footer class="foot">Natural State take-home · Generated from the notebook outputs by <code>src/dashboard.py</code></footer>
</div>
</div>
<script>{js}</script>
</body>
</html>
"""


# Redirects so a static server opens the dashboard at "/": outputs/index.html (server rooted at outputs/)
# and index.html in the project root (plain `python -m http.server 8000`). file:// needs the page named.
def _redirect(rel: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Natural State results</title>
<meta http-equiv="refresh" content="0; url={rel}index.html">
<script>location.replace(location.protocol === 'file:' ? '{rel}index.html' : '{rel}');</script>
</head>
<body><p><a href="{rel}index.html">Open the results dashboard</a></p></body>
</html>
"""


REDIRECT = _redirect("dashboard/")


def build_dashboard(project_root: Path) -> list[Path]:
    """Write the four dashboard pages into <project_root>/outputs/dashboard and return their paths.

    Also writes manifest.json and the outputs ZIP beside them, plus redirects at outputs/index.html
    and <project_root>/index.html so either server root opens the dashboard at "/".
    """
    root = Path(project_root)
    out = root / "outputs"
    target = out / "dashboard"
    target.mkdir(parents=True, exist_ok=True)
    birds, veg = load_birds(root), load_vegetation(root)
    dates = survey_dates(root)
    project = veg["project"] if veg else "Natural State"
    pages = {"index.html": ("Results overview", overview_page(birds, veg, dates)),
             "birds.html": ("Birds results", birds_page(birds)),
             "vegetation.html": ("Vegetation QA results", vegetation_page(veg, dates)),
             "files.html": ("Files and reproducibility", files_body(root, target))}
    written = []
    for name, (title, body) in pages.items():
        path = target / name
        path.write_text(page(title, name, body, project, dates), encoding="utf-8")
        written.append(path)
    (out / "index.html").write_text(REDIRECT, encoding="utf-8")
    (root / "index.html").write_text(_redirect("outputs/dashboard/"), encoding="utf-8")
    return written


if __name__ == "__main__":
    for p in build_dashboard(Path(__file__).resolve().parents[1]):
        print("wrote", p)
