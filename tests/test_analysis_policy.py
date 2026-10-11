"""Pytest checks for scientific policy, estimator failures and sampling semantics."""
import numpy as np
import pandas as pd
import pytest

from src.birds import (
    apply_support_policy,
    bin_weighted_precision,
    firth_sensitivity,
    fit_firth,
    label_predictions,
)
from src.vegetation import accumulation, recompute_species_quadrats


@pytest.mark.parametrize(
    "outcomes",
    [np.ones(20), np.zeros(20), np.r_[np.zeros(10), np.ones(10)]],
    ids=["all_correct", "all_incorrect", "complete_separation"],
)
def test_firth_converges_for_single_outcome_and_separation(outcomes):
    fit = fit_firth(pd.DataFrame({"outcome": outcomes, "logit": np.linspace(-2, 4, 20)}))
    assert fit["converged"]
    assert np.isfinite([fit["b0"], fit["b1"]]).all()
    assert fit["max_abs_modified_score"] <= 1e-8


@pytest.mark.parametrize(
    "data",
    [
        {"outcome": [1] * 4, "confidence": [.5] * 4},
        {"outcome": [1, 0, 1, 0], "confidence": [.2, .4, np.nan, .8]},
        {"outcome": [1, 2, 1, 0], "confidence": [.2, .4, .6, .8]},
        {"outcome": [1, 0, 1, 0], "confidence": [.2, .4, .6, 1.2]},
    ],
    ids=["constant_score", "missing_score", "nonbinary_outcome", "out_of_range_score"],
)
def test_firth_rejects_rank_deficiency_and_invalid_values(data):
    with pytest.raises(ValueError):
        fit_firth(pd.DataFrame(data))


def test_failed_firth_fit_cannot_export_a_cutoff():
    validation = pd.DataFrame({'commonName': ['Bird'] * 20, 'outcome': [1] * 20, 'confidence': np.linspace(0.1, 0.9, 20)})
    predictions = pd.DataFrame({'common_name': ['Bird'], 'confidence': [0.99]})
    table = firth_sensitivity(validation, predictions, max_iter=1)
    assert not table.loc['Bird', 'firth_converged']
    assert np.isnan(table.loc['Bird', 'firth_conf_threshold'])
    assert table.loc['Bird', 'firth_candidates'] == 0


def test_sparse_errors_keep_high_probability_candidate_unconfirmed():
    models = pd.DataFrame([{'species': 'Plover', 'n': 150, 'n_correct': 149, 'fit_status': 'ok', 'converged': True, 'b0': 5.2, 'b1': 0.55, 'conf_threshold': 0.26, 'threshold_within_val_range': True}]).set_index('species')
    validation = pd.DataFrame({'commonName': ['Plover', 'Plover'], 'confidence': [0.1, 0.99], 'outcome': [0, 1]})
    registry = apply_support_policy(models, validation)
    result = label_predictions(pd.DataFrame({'common_name': ['Plover'], 'confidence': [0.9]}), registry)
    assert result.loc[0, 'candidate_observation'] == 'Plover'
    assert result.loc[0, 'observation'] == 'unconfirmed'
    assert result.loc[0, 'model_status'] == 'pending_review_sparse_errors'


def test_one_outcome_cannot_become_ordinary_glm_observation():
    models = pd.DataFrame([{'species': 'Oriole', 'n': 150, 'n_correct': 150, 'fit_status': 'not fitted: single outcome', 'conf_threshold': float('nan'), 'threshold_within_val_range': False}]).set_index('species')
    validation = pd.DataFrame({'commonName': ['Oriole'], 'confidence': [0.99], 'outcome': [1]})
    registry = apply_support_policy(models, validation)
    result = label_predictions(pd.DataFrame({'common_name': ['Oriole'], 'confidence': [0.999]}), registry)
    assert result.loc[0, 'observation'] == 'unconfirmed'


def test_unchecked_score_bins_are_reported_as_uncovered():
    validation = pd.DataFrame({'commonName': ['Bird'], 'confidence': [0.2], 'outcome': [1]})
    predictions = pd.DataFrame({'common_name': ['Bird', 'Bird'], 'confidence': [0.2, 0.8]})
    summary, _ = bin_weighted_precision(validation, predictions)
    assert summary.loc[0, 'uncovered_prediction_share'] == pytest.approx(0.5)
    assert summary.loc[0, 'missing_bin_scenario_low'] == pytest.approx(0.5)
    assert summary.loc[0, 'missing_bin_scenario_high'] == pytest.approx(1.0)


def test_species_summary_uses_known_or_named_additional_entries():
    survey = pd.DataFrame({'submission_key': ['s']})
    quadrats = pd.DataFrame({'KEY': ['q1', 'q2', 'q3'], 'PARENT_KEY': ['s'] * 3, 'herb_species-selected_herb_species_uuids': ['uuid', None, None]})
    extras = pd.DataFrame({'PARENT_KEY': ['q2', 'q3'], 'validated_name': ['herb_001', None]})
    result = recompute_species_quadrats(survey, quadrats, extras)
    assert result.loc[0, 'recomputed_quadrats_with_species'] == 2


def test_actual_empty_quadrat_counts_but_missing_quadrats_are_not_padded():
    curve = accumulation([{'Species A'}, set()], n_perm=20)
    assert len(curve) == 2
    assert curve[-1] == 1
