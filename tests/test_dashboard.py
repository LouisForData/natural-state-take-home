"""Checks for the static results dashboard (src/dashboard.py) built from a copy of outputs/."""
import json
import re
import shutil
from pathlib import Path
from urllib.parse import unquote

import pandas as pd
import pytest

from src.dashboard import build_dashboard, load_vegetation
from src.transect_map import transect_priorities

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
RAW_NEEDED = ["validation_results.csv", "centroids.csv"]
PAGES = ["index.html", "birds.html", "vegetation.html", "files.html"]

pytestmark = pytest.mark.skipif(not (OUTPUTS / "veg_qa_flags.csv").exists() or not (OUTPUTS / "bird_thresholds.csv").exists(),
                                reason="run notebooks 01 and 02 first")


def _copy_project(dest: Path, skip=lambda name: False) -> Path:
    shutil.copytree(OUTPUTS, dest / "outputs", ignore=lambda d, names: [n for n in names if n == "dashboard" or skip(n)])
    (dest / "data" / "raw").mkdir(parents=True)
    for name in RAW_NEEDED:
        if (ROOT / "data" / "raw" / name).exists():
            shutil.copy(ROOT / "data" / "raw" / name, dest / "data" / "raw" / name)
    return dest


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = _copy_project(tmp_path_factory.mktemp("project"))
    paths = build_dashboard(root)
    return root, {p.name: p.read_text(encoding="utf-8") for p in paths}


def test_build_writes_all_pages(built):
    root, pages = built
    assert sorted(pages) == sorted(PAGES)
    assert all((root / "outputs" / "dashboard" / name).is_file() for name in PAGES)


def test_pages_show_values_read_from_the_csvs(built):
    root, pages = built
    out = root / "outputs"
    labels = pd.read_csv(out / "bird_label_summary.csv").set_index("common_name")
    nightjar = f'{int(labels.at["Abyssinian Nightjar", "observations"]):,}'
    assert nightjar in pages["birds.html"] and nightjar in pages["index.html"]
    assert f'{int(labels.predictions.sum()):,}' in pages["birds.html"]
    flags = pd.read_csv(out / "veg_qa_flags.csv")
    assert f"{len(flags):,} flag rows" in pages["vegetation.html"]
    q04 = int((flags.rule_id == "Q04").sum())
    assert re.search(rf'<code>Q04</code>.*?<div class="bn">{q04}</div>', pages["vegetation.html"])


def test_pages_need_no_network(built):
    _, pages = built
    for name, text in pages.items():
        urls = [u for u in re.findall(r"https?://[^\s\"'<>)]+", text) if u != "http://www.w3.org/2000/svg"]
        assert urls == [], f"{name} references {urls[:3]}"
        assert "<link" not in text and "src=\"http" not in text
    assert 'href="../transect_map.html"' in pages["vegetation.html"]


def test_outputs_root_redirects_to_dashboard(built):
    root, _ = built
    redirect = (root / "outputs" / "index.html").read_text(encoding="utf-8")
    assert 'url=dashboard/index.html' in redirect and "'dashboard/'" in redirect
    assert (root / "outputs" / "dashboard" / "index.html").is_file()


def test_theme_toggle_and_storage_key_present(built):
    _, pages = built
    for text in pages.values():
        assert 'id="theme-toggle"' in text and "aria-pressed" in text
        assert "localStorage.getItem('ns-theme')" in text and "localStorage.setItem('ns-theme'" in text


def test_review_priority_matches_the_transect_map(built):
    root, pages = built
    out = root / "outputs"
    qa = json.loads((out / "vegetation_qa_parameters.json").read_text())
    from_map = transect_priorities(pd.read_csv(out / "vegetation_transect_geometry.csv"), pd.read_csv(out / "veg_plot_summary.csv"),
                                   pd.read_csv(out / "veg_qa_flags.csv"), qa).priority.value_counts().to_dict()
    assert load_vegetation(root)["counts"] == from_map
    for status, label in [("critical", "Critical"), ("serious", "Serious"), ("warning", "Warning"), ("good", "No spatial flags")]:
        assert f'<option value="{status}">{label} ({from_map.get(status, 0)})</option>' in pages["vegetation.html"]
    rows = re.findall(r'<tr data-priority="(\w+)">', pages["vegetation.html"])
    assert pd.Series(rows).value_counts().to_dict() == from_map


def test_missing_bird_outputs_still_build_with_notice(tmp_path):
    root = _copy_project(tmp_path, skip=lambda name: name.startswith(("bird_", "birdnet_")))
    pages = {p.name: p.read_text(encoding="utf-8") for p in build_dashboard(root)}
    assert "Run notebook 01 first" in pages["index.html"] and "Run notebook 01 first" in pages["birds.html"]
    assert "Run notebook 02 first" not in pages["vegetation.html"] and "Plot review queue" in pages["vegetation.html"]


def test_files_page_lists_every_output_and_downloads_resolve(built):
    root, pages = built
    out = root / "outputs"
    files = [p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()
             and "dashboard" not in p.relative_to(out).parts and p.relative_to(out).as_posix() != "index.html"]
    missing = [f for f in files if f'href="../{f}"' not in pages["files.html"]]
    assert files and missing == []
    downloads = re.findall(r'href="([^"]+)" download', pages["files.html"])
    assert len(downloads) >= len(files)
    dashboard = out / "dashboard"
    assert all((dashboard / unquote(h)).resolve().is_file() for h in downloads)


def test_previews_are_embedded_capped_and_accurate(built):
    root, pages = built
    out = root / "outputs"
    text = pages["files.html"]
    data = json.loads(re.search(r'<script type="application/json" id="preview-data">(.*?)</script>', text, re.S).group(1))
    csvs = {name: p for name, p in data.items() if name.endswith(".csv")}
    assert csvs
    for name, p in csvs.items():
        assert len(p["rows"]) <= 15
        assert p["total"] == len(pd.read_csv(out / name)), name
    assert len(text.encode("utf-8")) < 1.5 * 1024 * 1024
    assert all("fetch(" not in page for page in pages.values())
