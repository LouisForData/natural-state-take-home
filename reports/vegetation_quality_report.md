# Vegetation quality report

The exports contain **32 submissions across 30 surveyed plots**. Two explicitly rejected submissions are retained for QA but excluded from ecological summaries. QA covers 640 quadrat records; ecological summaries cover 30 non-rejected submissions and 600 quadrats. Findings flag records for review and never correct original observations.

## Survey summary

All 13 summary integrity checks pass and asserted primary keys are unique. ODK parent keys and entity UUIDs connect surveys, quadrats, additional-species repeats, registered plots and planned centroids. Reconstructing the form's displayed species list matches all 640 quadrats. That verifies the derivation against the export; it does not verify taxonomic truth.

There are **307 issue rows: one error, 271 warnings and 35 informational flags**. Counts refer to findings, so a record can have several flags. The error is a blank species name on Plot 28. Twenty-three submissions have a stored `quadrats_with_species` calculation that differs from a reconstruction using selected known species or named additional-species repeats. These are warnings about derived data. Form versions, calculations, edits or exports may explain them; the cause is unresolved.

All 32 submissions retain a +02:00 device offset rather than expected EAT +03:00. This is informational: the offset alone proves neither a wrong nor a correct clock. Blank optional comments and genuinely empty quadrats are legitimate.

## Plot summary and spatial review

All 30 viable recorded transects depart by more than the analyst's 15-degree review tolerance from north–south. Bearings range from about 49.7 to 130.7 degrees, with median 103.8 degrees. The SOP allows rotation for obstacles or hazards; these exports do not establish the justification. This systematic pattern merits a project-level review, together with plot-level flags.

Finite-segment geometry identifies 127 quadrats outside the recorded belt plus the configured GPS allowance; 33 of these lie beyond recorded endpoints. Geometry flags are review signals, not a diagnosis of their cause.

The table lists all 30 non-rejected submissions, one per surveyed plot, highest review priority first. Review priority uses the same rule as the interactive map: **critical** when half or more of a plot's quadrats lie off the registered line; **serious** at a quarter or more, or a midpoint more than 25 m from the planned point; **warning** for a recorded length outside 45–55 m or any quadrat off the line. Provisional richness counts names as entered. Notebook 02 regenerates this table as `outputs/veg_plot_review_table.csv`.

|   Plot | Review priority   |   Quadrats |   With herbs |   Provisional richness |   Errors |   Warnings |   Info |   Quadrats off the line |   Median distance (m) |   Length (m) |   Bearing (°) |   New taxa, last 5 quadrats |
|-------:|:------------------|-----------:|-------------:|-----------------------:|---------:|-----------:|-------:|------------------------:|----------------------:|-------------:|--------------:|----------------------------:|
|     05 | Critical          |         20 |           19 |                     17 |        0 |         21 |      1 |                      19 |                  22.1 |           46 |           117 |                         2.8 |
|     27 | Critical          |         20 |           20 |                     22 |        0 |         16 |      1 |                      12 |                  14   |           29 |            56 |                         1.8 |
|     13 | Critical          |         20 |           20 |                     12 |        0 |         11 |      1 |                      11 |                  11.5 |           56 |            78 |                         0.7 |
|     07 | Serious           |         20 |           20 |                     18 |        0 |         10 |      1 |                       9 |                  10.2 |           52 |            85 |                         1.5 |
|     19 | Serious           |         20 |           19 |                     19 |        0 |         11 |      1 |                       9 |                   8.2 |           23 |            60 |                         2.6 |
|     14 | Serious           |         20 |           20 |                     19 |        0 |          9 |      1 |                       7 |                   8.7 |           44 |            91 |                         2.6 |
|     06 | Serious           |         20 |           20 |                     26 |        0 |          6 |      2 |                       6 |                   5.5 |           48 |           106 |                         3.5 |
|     08 | Serious           |         20 |           20 |                     31 |        0 |          8 |      1 |                       6 |                   7.4 |           48 |           112 |                         4.5 |
|     01 | Serious           |         20 |           20 |                     32 |        0 |         14 |      1 |                       5 |                   9.8 |           63 |           131 |                         4.3 |
|     04 | Serious           |         20 |           19 |                     20 |        0 |          6 |      1 |                       5 |                   4.3 |           53 |           110 |                         2.5 |
|     15 | Warning           |         20 |           20 |                     22 |        0 |          6 |      1 |                       4 |                   4   |           60 |            96 |                         4   |
|     26 | Warning           |         20 |           20 |                     23 |        0 |          5 |      1 |                       4 |                   5.7 |           50 |           113 |                         2.1 |
|     30 | Warning           |         20 |           20 |                     25 |        0 |          6 |      1 |                       4 |                   7.3 |           51 |           110 |                         3.3 |
|     03 | Warning           |         20 |           18 |                     15 |        0 |          3 |      1 |                       3 |                   5.6 |           57 |           107 |                         2   |
|     09 | Warning           |         20 |           20 |                     29 |        0 |          9 |      1 |                       2 |                   7   |           46 |            78 |                         4.2 |
|     10 | Warning           |         20 |           20 |                     21 |        0 |          3 |      1 |                       2 |                   3.6 |           57 |           109 |                         2.9 |
|     11 | Warning           |         20 |           20 |                     25 |        0 |          4 |      1 |                       2 |                   3.7 |           42 |           108 |                         2.3 |
|     12 | Warning           |         20 |           20 |                     40 |        0 |          4 |      1 |                       2 |                   5.2 |           42 |           123 |                         5.7 |
|     20 | Warning           |         20 |           20 |                     17 |        0 |         10 |      1 |                       2 |                   5.6 |           45 |           105 |                         1.6 |
|     21 | Warning           |         20 |           20 |                     30 |        0 |          5 |      1 |                       2 |                   4.6 |           45 |            98 |                         3.2 |
|     22 | Warning           |         20 |           20 |                     21 |        0 |          5 |      1 |                       2 |                   3.1 |           66 |            50 |                         2.2 |
|     25 | Warning           |         20 |           20 |                     31 |        0 |          5 |      2 |                       2 |                   2.6 |           43 |            96 |                         3.4 |
|     29 | Warning           |         20 |           20 |                     24 |        0 |         14 |      1 |                       2 |                   2.4 |           62 |           105 |                         2.7 |
|     18 | Warning           |         20 |           20 |                     28 |        0 |          8 |      1 |                       1 |                   4.4 |           46 |           114 |                         4   |
|     46 | Warning           |         20 |           20 |                      9 |        0 |          2 |      2 |                       1 |                   4.9 |           47 |           102 |                         0.8 |
|     16 | Warning           |         20 |           20 |                     23 |        0 |          4 |      1 |                       0 |                   1.6 |           58 |           100 |                         2.3 |
|     28 | Warning           |         20 |           19 |                     22 |        1 |          4 |      1 |                       0 |                   4.6 |           40 |           118 |                         3.6 |
|     02 | No spatial flags  |         20 |           19 |                     19 |        0 |          2 |      1 |                       0 |                   1.8 |           54 |           103 |                         2   |
|     17 | No spatial flags  |         20 |           20 |                     22 |        0 |          0 |      1 |                       0 |                   5.1 |           50 |            82 |                         2.6 |
|     24 | No spatial flags  |         20 |           20 |                     11 |        0 |          1 |      1 |                       0 |                   4.6 |           51 |            93 |                         1.7 |

The highest priority is to compare field layout, registered endpoints and quadrat locations for these plots. Per-submission roll-ups retain the link to individual findings. Plot summaries retain rejected status and do not merge repeated submissions away.

## Sampling effort

All 30 non-rejected submissions contain the prescribed 20 actual quadrats. Random-order accumulation uses these actual sampling units, including real empty quadrats; it never pads missing units. Plot 12 adds about 5.72 taxa in its final five quadrats on the mean curve. Plots 08, 01, 09 and 15 add about 4.46, 4.28, 4.18 and 4.02 taxa respectively. Continued accumulation identifies useful sampling-review priorities. The 10% tail-share category is an analyst heuristic, not proof of ecological adequacy.

Twenty-nine of 36 primary locations were surveyed. Plot 23 is registered non-viable because it is on private property. Backup Plot 46 was surveyed, but no supplied replacement crosswalk proves which primary it replaces. Primaries 31–36 have no registration or survey in the supplied exports and cluster to the north-east. Dataset coverage is incomplete; form completion alone cannot establish representation across locations, habitats or seasons.

Richness remains provisional. Original names are preserved, spelling variants can inflate counts, and unknown morphospecies are not assumed comparable across plots. Form display values and canonical entered names are stored separately.

![Actual-effort accumulation](../outputs/figures/B9_sampling_effort.png)

## Transect map

The [interactive map](https://louisfordata.github.io/natural-state-take-home/outputs/transect_map.html) and [GeoJSON](../outputs/transects.geojson) retain recorded geometry and planned locations. On the interactive map, transect colour shows spatial review priority, and hovering a transect or quadrat shows its measurements against SOP and analyst tolerances. Its off-line quadrat count (124 of 600) covers accepted submissions only; the 127 Q04 flags above also include the two rejected submissions. The static map shows coverage and review status without requiring web tiles.

![Recorded transects and planned coverage](../outputs/figures/B9_transect_map.png)

## Recommendation

Resolve the blank name, investigate the stored calculations, confirm systematic orientation and unusual plot geometry, and reconcile the planned-location/replacement register. Retain every original value and record any later reviewer decisions separately. Use ecological summaries as provisional descriptive evidence, with protocol completion and broader coverage explicitly distinguished.

**Evidence:** `veg_survey_summary.csv`, `veg_plot_summary.csv`, `veg_sampling_effort.csv`, `veg_qa_flags.csv`, `vegetation_form_calculation_audit.csv`, `vegetation_project_patterns.csv`, `vegetation_spatial_rollup.csv`, `vegetation_plot_coverage.csv` and `veg_plot_review_table.csv` in [outputs](../outputs/). Sources: supplied brief, ODK form workbooks and the two SOPs in `data/`; see [notebook 02](../notebooks/02_vegetation_quality_checks.ipynb) for calculations.
