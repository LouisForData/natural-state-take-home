# Vegetation technical handover

Load immutable ODK exports, construct derived audit views, then generate review findings and ecological summaries with explicit inclusion rules. A warning must not trigger an automatic correction of the original field record.

## Keys and inclusion

| Relationship | Join |
|---|---|
| Survey → quadrat repeat | Survey `KEY` to quadrat `PARENT_KEY` |
| Quadrat → additional species | Quadrat `KEY` to repeat `PARENT_KEY` |
| Survey → registered plot entity | Selected plot UUID to `vegplots.__id` |
| Registered plot → planned location | Centroid UUID to planned-centroid `__id` |
| Selected/reused species → entity list | Species UUID to the applicable list `__id` |

Assert primary-key uniqueness and expected join cardinality before counting records. Human-readable names are display values. QA includes all submissions; ecological summaries exclude only explicitly rejected submissions under this analysis policy. Within-submission unknown taxa remain visible; cross-plot richness curves exclude incomparable unknown labels.

## Reusable components

`src/vegetation.py` provides `build_transects`, `recompute_species_quadrats`, `build_flags`, `spatial_rollup` and `accumulation`. `src/transect_map.py` provides `build_transect_map`, which draws the interactive review map from the same tables without altering coordinates. Notebook 02 shows the staging columns expected by these functions and the form-derived species reconstruction. Raw tables are never edited.

The stored species-quadrat summary is recomputed from the form definition: a quadrat has selected known species or at least one additional repeat with a named `validated_name`. Preserve stored and recomputed values together; do not substitute one silently.

`veg_qa_flags.csv` contains `flag_id`, `rule_id`, `severity`, `level`, `plot_name`, `submission_key`, `record_key`, `field`, `value` and `message`. A stable flag ID hashes rule, record and field. The rule catalogue and parameter JSON identify `vegetation-qa-v2`; persist them with flags and input version. Store reviewer status and explanations separately rather than overwriting generated flags.

## Rule meaning

| Rule or parameter | Interpretation |
|---|---|
| SP00 | Blank species name: error |
| SP05 | Stored calculation differs from repeat reconstruction: warning, cause unresolved |
| P02 | Orientation differs from north–south by >15°: warning; review SOP exception justification |
| Q04 | Distance to finite recorded segment exceeds 2.5 m belt half-width + quadrat accuracy + 5 m endpoint allowance: warning |
| S05 | Device offset differs from expected +03:00: informational |
| 45–55 m length, 20–240 min duration, 10% accumulation tail | Analyst review heuristics, not prescribed scientific adequacy thresholds |
| 20 quadrats, 50 m × 5 m belt, midpoint within 25 m of planned centroid | SOP design expectations; measured geometry still needs uncertainty-aware review |

GPS allowances are screening tolerances, not formal error propagation. Plot-level geometry flags may have no survey key; preserve their registration record key and plot link. An issue total counts flags, not distinct bad records.

## Verification and review

For the current input version, expect 32 submissions, 640 quadrats and 307 QA rows; ecological analysis uses 30 submissions and 600 quadrats. Expect 23 stored-calculation warnings, 30 orientation warnings and 127 Q04 flags. Form-display reconstruction should match 640/640 records, and actual-effort curves should use exactly the observed units. Geometry exports are written once per run.

Confirm form versions/calculation history; field rotation justifications; unusual endpoints and quadrat captures; the +02:00 offset's meaning; missing planned locations and backup crosswalk; and taxonomy review. [The findings report](vegetation_quality_report.md) prioritises these questions. Do not infer fixes from the flags alone.

## Dashboard prototype

`src/dashboard.py` writes a static four-page dashboard to `outputs/dashboard/`, with images in `outputs/dashboard/assets/` (run by the last cell of notebook 02, or `python -m src.dashboard`). It reads exported files only and adds no analysis. Review priority comes from `transect_priorities()` in `src/transect_map.py`, so the dashboard and the interactive map cannot disagree. Run notebook 01 first; without bird outputs the bird panels show a notice instead.

| Page and panel | Source |
|---|---|
| Vegetation · headline numbers and answer | `veg_survey_summary.csv`, `veg_plot_summary.csv`, `vegetation_plot_coverage.csv`, `vegetation_transect_geometry.csv` |
| Vegetation · where to look first (plot map) | `vegetation_transect_geometry.csv`, `veg_plot_summary.csv`, `vegetation_plot_coverage.csv`, `data/raw/centroids.csv` |
| Vegetation · project-level findings and priority rules | `vegetation_project_patterns.csv`, `vegetation_plot_coverage.csv`, `vegetation_qa_parameters.json` |
| Vegetation · QA flags by rule | `veg_qa_flags.csv`, `vegetation_rule_catalogue.csv` |
| Vegetation · sampling effort | `veg_sampling_effort.csv` |
| Vegetation · plot review queue | `veg_plot_summary.csv`, `vegetation_transect_geometry.csv`, `veg_sampling_effort.csv`, `veg_qa_flags.csv` |
| Birds · decisions, calibration, evidence and limits | `bird_thresholds.csv`, `bird_label_summary.csv`, `bird_validation_metrics.csv`, `bird_checked_cutoff_evidence.csv`, `bird_bin_weighted_precision.csv`, `bird_firth_sensitivity.csv`, `bird_validation_link_audit.csv`, `data/raw/validation_results.csv` |
| Overview | The bird and vegetation sources above |
| Files | `src/dashboard_files.py`: every notebook, output, report and code file Git publishes (git-ignored raw inputs are left out), grouped and filterable, with previews embedded at build time, downloads of the real files, `manifest.json` and a ZIP of `outputs/` |
