"""Files page for the results dashboard: what each evidence file is, an embedded preview, and a download.

Only files that exist are listed. Previews are cut down and embedded at build time, so they work
offline and from file://; Download links point at the real files with relative URLs. Content is
embedded as JSON and rendered as text by dashboard.js; it is never interpreted as HTML or script.
"""
from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from src.dashboard_charts import esc

PREVIEW_ROWS = 50
PREVIEW_CELL_CHARS = 200
PREVIEW_TEXT_CHARS = 30_000
NOTEBOOK_SOURCE_CHARS = 3_000
NOTEBOOK_OUTPUT_CHARS = 1_500
NOTEBOOK_TOTAL_CHARS = 200_000
ZIP_NAME = "natural-state-outputs.zip"

# key: (title, subtitle, pill, folders shown as path chips)
GROUPS = {
    "notebooks": ("Analysis notebooks", "Primary reproducible analysis and exported results", "Analysis", ["notebooks/"]),
    "inputs": ("Input data and documentation", "Original, unchanged source records, SOPs and references", "Inputs",
               ["data/raw/", "data/reference/"]),
    "bird": ("BirdNET evidence files", "Thresholds, labels, checked-sample precision and audit records", "Outputs", ["outputs/"]),
    "veg": ("Vegetation QA files", "Rule-level flags, plot geometry, coverage and review priorities", "Outputs", ["outputs/"]),
    "figures": ("Generated figures and reports", "Static figures from the notebooks and the authored reports", "Outputs",
                ["outputs/figures/", "reports/"]),
    "config": ("Reproducibility and configuration", "Environment, tests and the code that builds every output", "Code",
               ["./", "src/", "tests/"]),
    "other": ("Other outputs", "Files in outputs/ without a description yet", "Outputs", ["outputs/"]),
}
FILTERS = [("all", "All files"), ("notebooks", "Notebooks"), ("birdnet", "BirdNET"), ("vegetation", "Vegetation"), ("methods", "Methods")]

DESCRIPTIONS = {
    # notebooks
    "notebooks/01_bird_analysis.ipynb": "Calibration, threshold fitting, species review and validation audit",
    "notebooks/02_vegetation_quality_checks.ipynb": "Survey completeness, spatial alignment, QA rules, sampling effort and this dashboard",
    # inputs: what is published, and the fingerprints of what is not
    "data/README.md": "How the supplied inputs are handled, and why raw files are not published",
    "data/input_manifest.csv": "SHA-256 fingerprints and sizes of every supplied input and reference file",
    # raw inputs (listed only where present and not git-ignored)
    "data/raw/birdnet_predictions.csv": "BirdNET prediction scores and recording metadata",
    "data/raw/validation_results.csv": "Expert review outcomes used for calibration",
    "data/raw/herbaceous_veg_survey.csv": "Survey submissions: one row per plot visit",
    "data/raw/herbaceous_veg_survey.xlsx": "ODK form definition for the herbaceous survey",
    "data/raw/herbaceous_veg_survey-quadrat_repeat.csv": "Quadrat records nested under each survey",
    "data/raw/herbaceous_veg_survey-additional_species_repeat.csv": "Additional species entered within quadrats",
    "data/raw/register_vegetation_plots.csv": "Plot registration submissions with transect endpoints",
    "data/raw/register_vegetation_plots.xlsx": "ODK form definition for plot registration",
    "data/raw/vegplots.csv": "Registered vegetation plot entities",
    "data/raw/centroids.csv": "Planned plot centroids with stratum and status",
    "data/raw/species.csv": "Species entity list used by the survey form",
    "data/raw/species_extra.csv": "Additional species list",
    "data/raw/species_extra_ids.csv": "Identifiers for the additional species list",
    "data/raw/surveys.csv": "Survey definitions",
    "data/raw/areas.csv": "Project areas (name and abbreviation)",
    "data/raw/projects.csv": "Project definitions",
    "data/raw/project_team.csv": "Project team members",
    "data/raw/ecosystem_types.csv": "Ecosystem type choices",
    "data/raw/transport.csv": "Transport choices recorded with surveys",
    "data/raw/README.md": "Where the raw inputs come from and how to place them",
    "data/reference/NS_-_Senior_Data_Scientist_-_Take_Home_Project.pdf": "The take-home brief",
    "data/reference/SOP__Herbaceous_Vegetation_Surveys___Natural_State_Docs.pdf": "SOP: herbaceous vegetation surveys",
    "data/reference/SOP__Vegetation_Plot_Registration___Natural_State_Docs.pdf": "SOP: vegetation plot registration",
    "data/reference/WoodKahl_2024_JOrnith_Guidelines_for_appropriate_use_of_BirdNET_scores.pdf":
        "Wood & Kahl (2024): guidelines for using BirdNET scores",
    "data/reference/README.md": "Reference documents used by the analysis",
    # bird outputs
    "outputs/birdnet_predictions_labelled.csv": "All BirdNET predictions with fitted threshold, P(correct) and observation label",
    "outputs/bird_label_summary.csv": "Predictions, fitted candidates and released observations per species",
    "outputs/bird_thresholds.csv": "Fitted P(correct) cutoffs, coefficients and support status by species",
    "outputs/bird_findings.json": "Machine-readable headline numbers behind the bird report",
    "outputs/bird_validation_metrics.csv": "Checked-sample precision per species with Wilson 95% interval",
    "outputs/bird_validation_score_bins.csv": "Validation sample by confidence bin, with prediction counts and weights",
    "outputs/bird_bin_weighted_precision.csv": "Precision re-weighted to the full prediction distribution",
    "outputs/bird_checked_cutoff_evidence.csv": "Checked outcomes and one-sided 95% lower bound at each cutoff",
    "outputs/bird_raw_cutoff_diagnostic.csv": "Checked precision and predictions retained at raw score cutoffs",
    "outputs/bird_clipping_sensitivity.csv": "How the cutoff moves with the probability clipping epsilon",
    "outputs/bird_firth_sensitivity.csv": "Firth-penalised fits as a check on separation",
    "outputs/bird_validation_link_audit.csv": "Validation-to-prediction record-link review",
    # vegetation outputs
    "outputs/veg_survey_summary.csv": "Survey-level counts: submissions, plots, quadrats, taxa and flags",
    "outputs/veg_plot_summary.csv": "Plot-level summaries, flag counts and spatial roll-up per submission",
    "outputs/veg_plot_review_table.csv": "Plot-level summary used in the report: effort, richness, flags, geometry and review priority",
    "outputs/veg_plot_review_table.md": "The same plot-level summary as a Markdown table",
    "outputs/veg_sampling_effort.csv": "Species accumulation per plot and an effort verdict",
    "outputs/veg_observations_long.csv": "Every species entry, one row per quadrat × species",
    "outputs/veg_qa_flags.csv": "Quality-assurance flags with rule, severity and record",
    "outputs/vegetation_rule_catalogue.csv": "QA rules with severity, basis and rule version",
    "outputs/vegetation_qa_parameters.json": "Tolerances used by the QA rules",
    "outputs/vegetation_integrity_checks.csv": "Join and key integrity checks",
    "outputs/vegetation_form_calculation_audit.csv": "Stored ODK quadrat counts against recomputed counts",
    "outputs/vegetation_species_derivation_mismatches.csv": "Species-display reconstruction mismatches (empty means all match)",
    "outputs/vegetation_form_catalogue.csv": "ODK form fields with constraints and calculations",
    "outputs/vegetation_plot_coverage.csv": "Planned centroids against registered and surveyed plots",
    "outputs/vegetation_project_patterns.csv": "Project-wide patterns with denominators",
    "outputs/vegetation_findings.json": "Machine-readable headline numbers behind the vegetation report",
    "outputs/vegetation_transect_geometry.csv": "Transect orientation, length, midpoint shift and endpoints",
    "outputs/vegetation_spatial_rollup.csv": "Quadrat distances from the registered line per submission",
    "outputs/transects.geojson": "Transect lines as GeoJSON for GIS tools",
    "outputs/transect_map.html": "Interactive transect review map (basemap needs internet)",
    # figures and reports
    "outputs/figures/A2_prediction_eda.png": "Prediction confidence by species",
    "outputs/figures/A3_validation_outcomes.png": "Expert outcome against BirdNET confidence",
    "outputs/figures/A5_baseline_fits.png": "Logistic baseline fits",
    "outputs/figures/A7_probability_intervals.png": "Probability-correct intervals",
    "outputs/figures/B3_quadrat_eda.png": "Quadrats per submission",
    "outputs/figures/B9_sampling_effort.png": "Sampling effort and species accumulation",
    "outputs/figures/B9_transect_map.png": "Static map of plots by status",
    "reports/bird_analysis.md": "Bird findings for Natural State",
    "reports/bird_tech_handover.md": "Bird technical handover",
    "reports/vegetation_quality_report.md": "Vegetation findings for Natural State",
    "reports/vegetation_tech_handover.md": "Vegetation technical handover, including the dashboard",
    "reports/decision_log.md": "Analysis decisions and their reasons",
    "reports/validation_notes.md": "How the analysis was executed and verified",
    # reproducibility and configuration
    "README.md": "Overview, setup and reading order",
    "requirements.txt": "Python package ranges",
    "environment_tested.json": "Package versions of the recorded test run",
    "pytest.ini": "Test configuration",
    "src/birds.py": "Calibration, labelling and validation functions",
    "src/vegetation.py": "Transect geometry, QA flags and accumulation functions",
    "src/common.py": "Input loading, fingerprints and evidence export",
    "src/transect_map.py": "Interactive transect map and the shared review-priority rule",
    "src/dashboard.py": "Builds the Overview, Birds and Vegetation pages",
    "src/dashboard_charts.py": "Hand-built SVG charts for the dashboard",
    "src/dashboard_files.py": "Builds this Files page, the manifest and the outputs ZIP",
    "src/dashboard_assets/dashboard.css": "Dashboard styles",
    "src/dashboard_assets/dashboard.js": "Dashboard behaviour: sorting, filters, previews",
    "tests/test_analysis_policy.py": "Regression tests for the analysis policy",
    "tests/test_dashboard.py": "Checks for the dashboard pages and file links",
}
CONFIG_FILES = ["README.md", "requirements.txt", "environment_tested.json", "pytest.ini"]
TYPE_NAMES = {".csv": "CSV", ".json": "JSON", ".geojson": "GEO", ".ipynb": "IPYNB", ".png": "PNG", ".jpg": "JPG",
              ".jpeg": "JPG", ".pdf": "PDF", ".md": "MD", ".txt": "TXT", ".py": "PY", ".ini": "INI", ".html": "HTML",
              ".xlsx": "XLSX", ".css": "CSS", ".js": "JS"}
TEXT_SUFFIXES = {".md", ".txt", ".py", ".ini", ".css", ".js"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif"}


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


# ---------------------------------------------------------------------------- inventory
def publishable(root: Path) -> set[str] | None:
    """Paths git would publish: tracked, or untracked but not ignored. None outside a git work tree.

    Keeps git-ignored files (raw inputs, reference PDFs) off the page, so a published site neither
    embeds excerpts of them nor links to files that are not there.
    """
    try:
        res = subprocess.run(["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                             capture_output=True, check=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return set(filter(None, res.stdout.decode("utf-8").split("\0")))


def _candidates(root: Path) -> list[Path]:
    """Every existing file the page could describe, before the git filter."""
    out = root / "outputs"
    found = []
    for folder, pattern in [("notebooks", "*.ipynb"), ("data", "*"), ("data/raw", "*"), ("data/reference", "*"), ("reports", "*.md"),
                            ("src", "*.py"), ("src/dashboard_assets", "*.*"), ("tests", "*.py")]:
        found += [p for p in sorted((root / folder).glob(pattern)) if p.is_file() and not p.name.startswith(".")]
    found += [root / name for name in CONFIG_FILES if (root / name).is_file()]
    if out.is_dir():
        found += [p for p in sorted(out.rglob("*")) if p.is_file() and not p.name.startswith(".")
                  and "dashboard" not in p.relative_to(out).parts and p.relative_to(out).as_posix() != "index.html"]
    return found


def list_files(root: Path) -> list[str]:
    """Project-relative paths the page lists: existing files, minus git-ignored ones inside a repository."""
    keep = publishable(root)
    rels = [p.relative_to(root).as_posix() for p in _candidates(root)]
    if keep is not None:
        rels = [r for r in rels if r in keep]
    order = {rel: i for i, rel in enumerate(DESCRIPTIONS)}  # curated order first, then alphabetical
    return sorted(rels, key=lambda rel: (order.get(rel, len(order)), rel))


def withheld(root: Path) -> list[str]:
    """Existing files left off the page because git ignores them (e.g. data/raw/, data/reference/)."""
    keep = publishable(root)
    return [] if keep is None else sorted(p.relative_to(root).as_posix() for p in _candidates(root)
                                          if p.relative_to(root).as_posix() not in keep)


def group_of(rel: str) -> str:
    name = rel.rsplit("/", 1)[-1]
    if rel.startswith("notebooks/"):
        return "notebooks"
    if rel.startswith("data/"):
        return "inputs"
    if rel.startswith(("outputs/figures/", "reports/")):
        return "figures"
    if rel.startswith("outputs/"):
        if name.startswith(("bird", "birdnet")):
            return "bird"
        if name.startswith(("veg", "vegetation", "transect")):
            return "veg"
        return "other"
    return "config"


def tags_of(rel: str, group: str) -> list[str]:
    """Filter-chip tags: notebooks, birdnet, vegetation, methods."""
    name = rel.rsplit("/", 1)[-1].lower()
    tags = {"notebooks": ["notebooks"], "bird": ["birdnet"], "veg": ["vegetation"], "config": ["methods"],
            "inputs": ["methods"], "figures": [], "other": []}[group]
    if any(k in name for k in ("bird", "validation_results")) or name.startswith(("a2_", "a3_", "a5_", "a7_")) or "01_" in name:
        tags.append("birdnet")
    if any(k in name for k in ("veg", "plot", "centroid", "species", "transect", "quadrat", "survey")) \
            or name.startswith(("b3_", "b9_")) or "02_" in name:
        tags.append("vegetation")
    if rel.startswith("reports/"):
        tags.append("methods")
    return sorted(set(tags))


# ---------------------------------------------------------------------------- previews
def _notebook_preview(path: Path) -> tuple[dict, str]:
    nb = json.loads(path.read_text(encoding="utf-8"))
    cells, used = [], 0
    for c in nb.get("cells", []):
        if used > NOTEBOOK_TOTAL_CHARS:
            cells.append({"type": "markdown", "source": "… preview stops here; download the notebook for the rest."})
            break
        src = "".join(c.get("source", ""))[:NOTEBOOK_SOURCE_CHARS]
        outs = []
        for o in c.get("outputs", []):
            if o.get("output_type") == "stream":
                text = "".join(o.get("text", ""))
            elif o.get("output_type") == "error":
                text = f'{o.get("ename", "")}: {o.get("evalue", "")}'
            else:
                data = o.get("data", {})
                text = "".join(data.get("text/plain", "")) if "text/plain" in data else ""
                if any(k.startswith("image/") for k in data):
                    text = "[figure: download the notebook to view it]"
            if text.strip():
                outs.append(text[:NOTEBOOK_OUTPUT_CHARS] + ("\n…" if len(text) > NOTEBOOK_OUTPUT_CHARS else ""))
        cells.append({"type": c.get("cell_type", "code"), "source": src, "count": c.get("execution_count"), "outputs": outs})
        used += len(src) + sum(map(len, outs))
    n = len(nb.get("cells", []))
    return {"kind": "notebook", "cells": cells, "note": "read-only, saved outputs; code is not run"}, f"{n} cells"


def preview_for(path: Path) -> tuple[dict, str]:
    """(preview record without href/name, meta text such as rows · cols)."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            df = pd.read_csv(path, dtype=str, keep_default_na=False)
            rows = df.head(PREVIEW_ROWS).map(lambda x: x[:PREVIEW_CELL_CHARS]).values.tolist()
            note = f"first {len(rows)} of {len(df):,} rows" if len(df) > len(rows) else f"all {len(df):,} rows"
            header = ["" if c.startswith("Unnamed: ") else c for c in df.columns]
            return ({"kind": "table", "header": header, "rows": rows, "total": len(df), "note": note},
                    f"{len(df):,} row{'' if len(df) == 1 else 's'} · {df.shape[1]} cols")
        if suffix in (".json", ".geojson"):
            data = json.loads(path.read_text(encoding="utf-8"))
            text = json.dumps(data, indent=2, ensure_ascii=False)
            cut = len(text) > PREVIEW_TEXT_CHARS
            meta = (f'{len(data.get("features", [])):,} features' if isinstance(data, dict) and data.get("type") == "FeatureCollection"
                    else f"{len(data)} fields" if isinstance(data, dict) else f"{len(data):,} items")
            return {"kind": "text", "text": text[:PREVIEW_TEXT_CHARS] + ("\n…" if cut else ""),
                    "note": f"first {PREVIEW_TEXT_CHARS // 1000} KB" if cut else ""}, meta
        if suffix == ".ipynb":
            return _notebook_preview(path)
        if suffix in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="replace")
            cut = len(text) > PREVIEW_TEXT_CHARS
            return {"kind": "text", "text": text[:PREVIEW_TEXT_CHARS] + ("\n…" if cut else ""),
                    "note": f"first {PREVIEW_TEXT_CHARS // 1000} KB" if cut else ""}, f"{text.count(chr(10)) + 1:,} lines"
        if suffix in IMAGE_SUFFIXES:
            return {"kind": "image"}, ""
        if suffix == ".pdf":
            return {"kind": "pdf"}, ""
        if suffix == ".html":
            return {"kind": "none", "reason": "HTML pages are not previewed here, so their scripts never run inside the "
                                              "dashboard. Use Open to view it in a new tab, or Download."}, ""
        if suffix == ".xlsx" and path.with_suffix(".csv").exists():
            return {"kind": "none", "reason": f"Spreadsheet preview is not available. The same records are in "
                                              f"{path.with_suffix('.csv').name}, which has a preview."}, ""
    except Exception as exc:  # unreadable file: still list it with a download
        return {"kind": "none", "reason": f"Preview failed ({type(exc).__name__}); the file can still be downloaded."}, ""
    return {"kind": "none", "reason": "Preview is not available for this file type. Use Download to get the file."}, ""


# ---------------------------------------------------------------------------- build
def href_for(rel: str) -> str:
    """Relative URL from outputs/dashboard/; outputs/ files stay reachable when only outputs/ is served."""
    return "../" + quote(rel[len("outputs/"):]) if rel.startswith("outputs/") else "../../" + quote(rel)


def build_inventory(root: Path) -> tuple[list[dict], dict]:
    """Manifest entries and embedded previews for every listed file."""
    entries, previews = [], {}
    for rel in list_files(root):
        path = root / rel
        group = group_of(rel)
        preview, meta = preview_for(path)
        size = _size(path.stat().st_size)
        kind = TYPE_NAMES.get(path.suffix.lower(), path.suffix.lstrip(".").upper()[:5] or "FILE")
        entry = {"path": rel, "name": path.name, "category": group, "tags": tags_of(rel, group), "type": kind,
                 "size_bytes": path.stat().st_size, "description": DESCRIPTIONS.get(rel, ""), "href": href_for(rel),
                 "meta": " · ".join(x for x in (meta, size) if x)}
        entries.append(entry)
        previews[rel] = {**preview, "name": path.name, "type": kind, "size": size, "href": entry["href"]}
    return entries, previews


def write_zip(root: Path, target: Path) -> Path | None:
    """Deterministic ZIP of outputs/ (without the dashboard), so rebuilds do not churn."""
    out = root / "outputs"
    files = [p for p in sorted(out.rglob("*")) if p.is_file() and "dashboard" not in p.relative_to(out).parts
             and p.relative_to(out).as_posix() != "index.html"]
    if not files:
        return None
    path = target / ZIP_NAME
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            info = zipfile.ZipInfo("outputs/" + p.relative_to(out).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, p.read_bytes())
    return path


def _row(e: dict) -> str:
    desc = (f'<div class="fdesc">{esc(e["description"])}</div>' if e["description"]
            else '<div class="fdesc missing">No description yet</div>')
    open_link = (f'<a class="btn ghost" href="{e["href"]}" target="_blank" rel="noopener">Open</a>'
                 if e["type"] == "HTML" else "")
    search = esc(f'{e["path"]} {e["description"]}'.lower())
    return (f'<li class="file" data-search="{search}" data-tags="{" ".join(e["tags"])}">'
            f'<span class="badge">{esc(e["type"])}</span>'
            f'<div class="fmain"><div class="fname">{esc(e["name"])}</div>{desc}<div class="fmeta">{esc(e["meta"])}</div></div>'
            f'<div class="factions"><button type="button" class="btn ghost" data-preview="{esc(e["path"])}" '
            f'aria-label="Preview {esc(e["name"])}">Preview</button>{open_link}'
            f'<a class="btn ghost" href="{e["href"]}" download="{esc(e["name"])}" '
            f'aria-label="Download {esc(e["name"])}">Download</a></div></li>')


def files_page(root: Path, target: Path) -> str:
    """Body of files.html. Also writes manifest.json and the outputs ZIP into ``target``."""
    entries, previews = build_inventory(root)
    withheld_files = withheld(root)
    (target / "manifest.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")
    zip_path = write_zip(root, target)
    cards = []
    for key, (title, sub, pill, paths) in GROUPS.items():
        rows = [e for e in entries if e["category"] == key]
        if not rows:
            continue
        folders = sorted({e["path"].rsplit("/", 1)[0] + "/" if "/" in e["path"] else "./" for e in rows},
                         key=lambda f: paths.index(f) if f in paths else len(paths))
        chips = "".join(f'<span class="path">{esc(f)}</span>' for f in folders)
        anchor = {"inputs": ' id="methods"'}.get(key, "")
        hidden = [w for w in withheld_files if w.startswith("data/")]
        tip = {"notebooks": "Run each notebook from a clean kernel (01, then 02); both rewrite their outputs and notebook 02 "
                            "rebuilds this dashboard.",
               "inputs": (f"{len(hidden)} raw input and reference files are not published with this repository "
                          "(see data/README.md); input_manifest.csv records their fingerprints. " if hidden else "")
                         + "Source inputs are read-only: each notebook fingerprints them and checks the bytes are unchanged "
                           "at the end."}.get(key)
        cards.append(f'<section class="card group"{anchor}><div class="ch"><div><h2>{title}</h2><div class="cs">{sub}</div>'
                     f'</div><span class="pill grey">{pill}</span></div>{chips}'
                     f'<ul class="files">{"".join(_row(e) for e in rows)}</ul>'
                     f'{f"<div class=tip>{tip}</div>" if tip else ""}</section>')
    chips = "".join(f'<button type="button" class="filter" data-tag="{t}" aria-pressed="{str(t == "all").lower()}">{label}</button>'
                    for t, label in FILTERS)
    zip_btn = (f'<a class="btn outline" href="{quote(zip_path.name)}" download>Download all outputs '
               f'(ZIP, {_size(zip_path.stat().st_size)})</a>' if zip_path else "")
    data = json.dumps(previews, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    n_out = sum(e["path"].startswith("outputs/") for e in entries)
    return f"""
<div class="answer">{_info_icon()}<div><b>Every file listed exists in this repository.</b> Preview shows an excerpt embedded
when the dashboard was built, so it works offline; Download serves the actual file with its original name.
{len(entries)} files, {n_out} of them in <code>outputs/</code>.</div></div>
<div class="answer" id="served-note" hidden>{_info_icon("warning")}<div><b>Served from <code>outputs/</code>.</b> Files outside
<code>outputs/</code> (notebooks, inputs, reports, code) are only reachable when the server runs from the project root:
<code>python -m http.server 8000</code>, then open <code>http://127.0.0.1:8000/</code>.</div></div>
<div class="files-top"><div class="filters" role="group" aria-label="Filter by category">{chips}</div>
<div class="actions" style="margin:0 0 16px"><label class="search"><svg width="14" height="14" viewBox="0 0 24 24" fill="none"
 stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/>
<path d="m20 20-3.5-3.5"/></svg><input id="file-filter" type="search" placeholder="Filter files…"
 aria-label="Filter files by name or description"></label>{zip_btn}</div></div>
<div class="fgrid">{"".join(cards)}</div>
<p class="empty" id="no-match" hidden>No files match that filter.</p>
<div class="two" style="margin-top:16px">
  <section class="card"><h2>How the pages connect to evidence</h2><div class="cs">A simple, auditable workflow</div>
    <div class="tip" style="margin:0 0 12px">Original inputs → notebooks 01 and 02 → evidence tables in <code>outputs/</code> →
    dashboard pages and figures.</div>
    <ul class="fl"><li>{_info_icon("good")}<span>Source files are not edited during analysis; the notebooks verify their
    fingerprints.</span></li><li>{_info_icon()}<span>Every dashboard panel names the output file its numbers come from.</span></li>
    <li>{_info_icon()}<span><code>manifest.json</code> beside this page lists every file shown here with its category and size.</span></li></ul>
  </section>
  <section class="card" id="reproducibility"><h2>Before submission</h2><div class="cs">Reproducibility checks to complete</div>
    <ol class="checks"><li>Run notebook 01, then notebook 02, each from a fresh kernel.</li>
    <li>Run <code>python -m pytest -v</code> and update the validation notes.</li>
    <li>Confirm the dashboard numbers against the files above (each panel cites its source).</li>
    <li>Check that raw inputs are unchanged: both notebooks end with a fingerprint check.</li></ol>
  </section>
</div>
<dialog id="preview" aria-labelledby="preview-title"><div class="dh"><div class="dt"><h2 id="preview-title"></h2><small></small></div>
<a class="btn outline dl" download>Download</a><button type="button" class="dclose" aria-label="Close preview">×</button></div>
<div class="db"></div></dialog>
<script type="application/json" id="preview-data">{data}</script>"""


def _info_icon(status: str = "info") -> str:
    icon = {"info": "i", "good": "✓", "warning": "!"}[status]
    return f'<i class="ic s-{status}" aria-hidden="true">{icon}</i>'
