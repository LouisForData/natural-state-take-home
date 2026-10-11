# Analysis decisions

This log records the current revision's choices. It is not a reconstructed chronology of commits.

| Decision | Reason | Consequence |
|---|---|---|
| Two explanatory notebooks with reusable `src/` functions | Keep the analysis easy to follow and the rules reusable | Notebook narrative and implementation can be reviewed together |
| Ordinary binomial GLM for the requested bird calibration | Match the supplied method and make support limits explicit | No silent substitute estimator for unsupported species |
| Separate fitted candidates from accepted observations | A numerical cutoff can have weak support | Plover's 538 candidates remain visible; final labels are unconfirmed |
| Five-error screening heuristic | Sparse errors make a cutoff unstable | Transparent exploratory policy, not a universal validity criterion |
| No p-value-only release criterion | Significance does not quantify performance at the target | Review evidence, range, uncertainty and validation design together |
| Preserve Oriole and Firefinch as unconfirmed | Single-outcome fit and unsupported target respectively | Unconfirmed does not imply absence |
| Exact bounds and bin weighting as conditional diagnostics | Same-data fitting and unclear sampling limit inference | No claim of independently certified 99% precision or recall |
| No approximate-link expert overrides | Rounded score and recording do not verify segment identity | Linkage audit remains evidence for clarification |
| SP05 warning; P02 warning and project summary | Distinguish derived discrepancy and systematic field-layout pattern | Causes remain unresolved rather than assigned to field error |
| Actual sampling units, including true empties | Missing repeats are not sampled empty quadrats | No artificial padding of effort curves |
| Preserve canonical entered names and separate display values | Form equivalence and taxonomic equivalence differ | Provisional richness and traceable reconstruction |
| Authored reports survive reruns | Regenerated tables must not erase reviewed interpretation | Reports require an explicit evidence review after each run |
| Firth estimator as a sensitivity diagnostic | Test dependence on the estimator without changing the observation policy | Nightjar cutoff 0.667 to 0.709; Plover 0.259 to 0.817; Oriole ordinary slope not estimable and Firth slope about -0.057 |
