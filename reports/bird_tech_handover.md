# Bird technical handover

When a BirdNET prediction enters the pipeline, retain its original values, apply the species model and store both its fitted candidate status and its policy-approved observation label. Unsupported species remain auditable as `unconfirmed`.

## Processing contract

1. Load the prediction and validation CSVs; validate score range, required columns and expert outcomes as demonstrated in notebook 01.
2. Use `fit_species_models(validation, predictions)` and `apply_support_policy(models, validation)` from `src/birds.py` to generate the per-species registry.
3. Use `label_predictions(predictions, registry)`. Never apply approximate clip-match overrides.
4. Persist labels with registry, input version and model/policy version. Produce checked-sample diagnostics separately from population claims.

| Output field | Meaning |
|---|---|
| Original prediction columns | Unchanged, with one output row for every input row |
| `p_correct` | Fitted mean probability; not a guaranteed precision |
| `candidate_observation` | Species name if fitted probability reaches 0.99, otherwise `unconfirmed` |
| `observation` | Candidate species only if `use_for_labels` is true; otherwise `unconfirmed` |
| `model_status` | Support or withholding reason from registry |
| `conf_threshold` | Fitted raw-score threshold where available |
| `score_outside_validation_range` | Prediction score exceeds the species' checked range |
| `needs_model_review` | Unsupported policy or out-of-range score |
| `model_version`, `policy_version` | `takehome-glm-v1`, `takehome-policy-v2` |

The current acceptance policy requires an ordinary converged fit with no fit warning, a positive slope, a cutoff within validated scores and at least five observed errors. These conditions are exploratory screening, not a production guarantee. Out-of-range prediction scores are retained with review flags; the exploratory observation field is not an automatic production approval.

## Required checks

- Output row count must remain 29,491 for these supplied inputs, with original prediction columns preserved in order.
- Every accepted observation must have fitted `p_correct >= 0.99` and registry eligibility.
- Current expected labels: 3,147 Nightjar observations; 538 Plover candidates and zero Plover observations; Oriole and Firefinch zero observations.
- Single-outcome, failed, warned or unsupported fits must not silently acquire accepted labels.
- Recall must remain unavailable until independently labelled missed-call data exist.

`tests/test_analysis_policy.py` checks important withholding and coverage behavior. The notebook supplies input assertions and raw-byte preservation checks.

## Separate sensitivity output

`firth_sensitivity(validation, predictions)` generates `bird_firth_sensitivity.csv`. Review `firth_converged`, `firth_fit_status`, iterations and modified-score residuals. Invalid inputs raise `ValueError`; non-converged fits have no usable coefficients or cutoff. A non-positive slope has no increasing cutoff. These fits do not feed the registry or observation field.

## Questions before deployment

Confirm BirdNET version, sensitivity and score-generation settings; validation selection and clip dependence; original recording/segment identifiers; and whether the validation set represents this deployment. Decide how the team will independently validate a locked cutoff and route review flags. Request clarification instead of translating `unconfirmed` to absence.

Read [bird findings](bird_analysis.md) for interpretation. Detailed evidence is in `outputs/bird_thresholds.csv`, `bird_checked_cutoff_evidence.csv`, `bird_validation_link_audit.csv` and `birdnet_predictions_labelled.csv`.
