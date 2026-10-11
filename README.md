# Natural State take-home

Two explanatory notebooks turn BirdNET predictions into auditable labels and vegetation exports into traceable quality findings. The notebooks follow **question, reason, code, result and decision**. Reusable rules live in `src/`; written conclusions live in `reports/`.

## Start here

For a quick review, download or clone this repository and open `outputs/dashboard/index.html` locally. The dashboard presents the saved results and provides previews and downloads. Reproducing the analysis requires the original input files supplied with the take-home brief.

1. Review [bird analysis](notebooks/01_bird_analysis.ipynb), then [vegetation quality checks](notebooks/02_vegetation_quality_checks.ipynb).
2. Read [bird findings](reports/bird_analysis.md) and [vegetation findings](reports/vegetation_quality_report.md).
3. Review the [bird technical handover](reports/bird_tech_handover.md) and [vegetation technical handover](reports/vegetation_tech_handover.md), together with the relevant CSV outputs and rule versions.
4. See the [analysis decisions](reports/decision_log.md) and [validation notes](reports/validation_notes.md) for assumptions, checks and remaining limitations.

## Folder responsibilities

| Location | Contents and ownership |
|---|---|
| `README.md` | Overview, setup and reading order |
| `notebooks/` | Bird and vegetation analysis notebooks, including saved results |
| `src/` | Reusable calibration, labelling, validation, geometry, map and dashboard functions |
| `reports/` | Authored findings, technical handovers, decisions and validation notes |
| `outputs/` | Generated labels, QA flags, summaries, figures, maps, GeoJSON and dashboard pages |
| `data/raw/` | Supplied input tables; read only and excluded from Git |
| `data/reference/` | Brief, SOPs and BirdNET paper; excluded from Git |
| `tests/` | Regression checks for analysis policies, sampling rules and dashboard behaviour |
| `environment_tested.json` | Earlier analysis environment and the verified local Windows test result |

## Run locally

Use Python 3.12 for the closest match to the documented environments. Open a terminal in the project folder.

Before running the notebooks, place the supplied input files in `data/raw/` using the filenames listed in `data/input_manifest.csv`. Raw inputs and reference documents are excluded from this GitHub repository. Use the original files supplied with the take-home brief.

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Or on macOS / Linux:

```bash
source .venv/bin/activate
```

Install packages, register a named notebook kernel, run the tests and open JupyterLab:

```bash
python -m pip install -r requirements.txt
python -m ipykernel install --user --name natural-state --display-name "Python (Natural State)"
python -m pytest -v
python -m jupyterlab
```

The suite contains **17 test functions and 22 test cases**: eight analysis-policy functions covering 13 cases, including parameterized scenarios, and nine dashboard tests.

The verified local Windows run on **11 October 2026** passed all **22 cases in 2.58 seconds**, using **Python 3.12.10** and **pytest 9.1.1**. This verifies the automated tests; it does not establish that both notebooks were executed in fresh Windows Jupyter kernels.

To run the test files separately:

```bash
python -m pytest tests/test_analysis_policy.py -v
python -m pytest tests/test_dashboard.py -v
```

Select **Python (Natural State)** in each notebook, then use **Restart Kernel and Run All Cells**. Run the bird notebook first, followed by the vegetation notebook. Both locate the project from either its root or the `notebooks/` folder.

Each analysis run fingerprints the raw inputs and checks that their bytes remain unchanged. Generated outputs are replaced on rerun. Authored Markdown reports are maintained separately: review the regenerated evidence and update report text deliberately.

See [validation notes](reports/validation_notes.md) for the earlier notebook execution method and the limits of environment verification. Dependencies have compatible version ranges. `environment_tested.json` preserves the earlier analysis package versions and records the local Windows pytest result separately; it is not a fully locked environment.

## Results dashboard

The dashboard contains four pages:

| Page | Contents |
|---|---|
| Overview | Headline findings and links to the analyses |
| Birds | Species decisions, calibration plots, candidate and observation counts, and supporting evidence |
| Vegetation | Spatial review priorities, project findings, sampling effort and a filterable plot review queue |
| Files | Embedded previews and downloads of generated outputs |

Open `outputs/dashboard/index.html` directly, or open `outputs/index.html`, which redirects to the dashboard. Dashboard pages, embedded charts and file previews work offline. The light/dark theme preference is remembered across pages where browser storage is available.

Rebuild the dashboard from the existing outputs:

```bash
python -m src.dashboard
```

The vegetation notebook also includes a final dashboard build cell. The dashboard reads existing analysis outputs rather than fitting models or changing QA rules.

To serve the saved results locally:

```bash
python -m http.server 8000 --bind 127.0.0.1 --directory outputs
```

Open <http://127.0.0.1:8000/>. Press **Ctrl+C** in the terminal to stop the server.

The full interactive `transect_map.html` uses external map tiles and JavaScript resources, so it requires internet access. A static map is available at `outputs/figures/B9_transect_map.png`.

## Current findings

- **Bird data:** 29,491 predictions and 551 expert checks. Nightjar's exploratory score cutoff is about 0.667 and produces 3,147 observations. Plover's fitted cutoff of about 0.259 gives 538 candidates, all withheld from final observations pending review. Oriole and Firefinch remain unconfirmed under this method.
- A fitted 99% correctness target is not independent certification of 99% population precision. Recall cannot be measured from these data.
- **Vegetation QA:** 32 submissions and 640 quadrats. Ecological summaries use 30 non-rejected submissions and 600 quadrats. There are 307 issue rows: one error, 271 warnings and 35 informational flags.
- Stored calculation discrepancies, systematic transect orientation, unusual quadrat geometry and missing planned locations need review. Completing 20 quadrats establishes protocol effort, not ecological adequacy.

## Key output files

| File in `outputs/` | Use |
|---|---|
| `birdnet_predictions_labelled.csv` | Original prediction rows with candidate and final observation labels |
| `bird_thresholds.csv` | Species coefficients, score cutoffs, fit support and policy versions |
| `bird_firth_sensitivity.csv` | Separate Firth estimates, convergence diagnostics and comparisons with GLM cutoffs |
| `bird_checked_cutoff_evidence.csv` | In-sample retained checks and exact lower bounds |
| `bird_bin_weighted_precision.csv` | Conditional reweighting and missing-bin scenarios |
| `veg_qa_flags.csv` | Stable rule and record identifiers for each finding |
| `vegetation_rule_catalogue.csv`, `vegetation_qa_parameters.json` | QA meanings, versions and tolerances |
| `vegetation_spatial_rollup.csv`, `vegetation_project_patterns.csv` | Submission and project-level spatial review findings |
| `veg_survey_summary.csv`, `veg_plot_summary.csv`, `veg_sampling_effort.csv` | Summary tables with explicit denominators |
| `transect_map.html` | Interactive transect review map |
| `transects.geojson` | Spatial interchange file |
| `figures/` | Static analysis and map figures |
| `dashboard/` | Four-page results dashboard with embedded previews and download links |
| `index.html` | Entry point that redirects to the dashboard |

## Data and AI use

Raw inputs and reference documents are excluded from Git by default; see `.gitignore`. To reproduce the analysis, use the original data supplied with the take-home brief and the filenames listed in `data/input_manifest.csv`. The manifest records input SHA-256 fingerprints. Keep source data unchanged.

Spatial outputs retain recorded coordinates. Coordinates appear in notebooks, maps and several generated files; they have not been silently corrected.

I used AI assistance for code organisation, explanations and review. Validation methods and unresolved analytical limitations are documented in `reports/validation_notes.md`.