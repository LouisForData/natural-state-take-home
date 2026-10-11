"""Species calibration, explicit acceptance policy, and validation diagnostics."""
import warnings
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import beta
from scipy.special import expit

TARGET_P = 0.99
EPS = 1e-4
SENSITIVITY = 1.0  # Must be confirmed against BirdNET run metadata.
POLICY_VERSION = 'takehome-policy-v2'
MODEL_VERSION = 'takehome-glm-v1'

def to_logit(conf, eps=EPS, sensitivity=SENSITIVITY):
    c = np.clip(np.asarray(conf, dtype=float), eps, 1 - eps)
    return np.log(c / (1 - c)) / sensitivity


def from_logit(x):
    return expit(np.asarray(x, dtype=float))





def separation_status(d: pd.DataFrame) -> str:
    wrong, right = d.loc[d["outcome"] == 0, "logit"], d.loc[d["outcome"] == 1, "logit"]
    if wrong.empty or right.empty:
        return "single outcome"
    if wrong.max() < right.min():
        return "complete separation"
    if wrong.max() == right.min():
        return "quasi separation"
    return f"overlap ({int((wrong >= right.min()).sum())} wrong ≥ lowest correct)"


def fit_glm(d: pd.DataFrame) -> dict:
    # Plain binomial GLM: outcome ~ logit(confidence). Returns coefficients + diagnostics.
    out = {"n": len(d), "n_correct": int(d["outcome"].sum()), "separation": separation_status(d)}
    if d["outcome"].nunique() < 2:
        out["fit_status"] = "not fitted: single outcome"
        return out
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            res = sm.GLM(d["outcome"], sm.add_constant(d["logit"]), family=sm.families.Binomial()).fit()
        except Exception as e:  # PerfectSeparationError etc.
            out["fit_status"] = f"failed: {type(e).__name__}"
            return out
    out.update(b0=res.params["const"], b1=res.params["logit"], se_b1=res.bse["logit"],
               converged=bool(res.converged), aic=res.aic, p_slope=res.pvalues["logit"],
               fit_status="ok" if not caught else "warning: " + "; ".join({str(w.message)[:70] for w in caught}))
    return out


def threshold(b0, b1, p=TARGET_P):
    # Logit score at which predicted P(correct) = p. NaN if the slope is missing or not positive.
    if b1 is None or not np.isfinite(b1) or b1 <= 0:
        return np.nan
    return (np.log(p / (1 - p)) - b0) / b1


def fit_firth(d, max_iter=200, tol=1e-8, max_step=5.0, max_halvings=30):
    """Fit Firth logistic regression as an estimator sensitivity diagnostic.

    Maximizes log likelihood + 0.5 * log det(Fisher information), using
    the modified score, Fisher scoring and objective-based step halving.
    Scores are transformed internally; a finite `logit` column is also accepted.
    Standardization improves conditioning; coefficients are returned on the
    original logit-score scale. Failed fits return NaN coefficients, never an
    apparently usable cutoff. This function does not change observation labels.

    Algorithm reference: CRAN logistf documentation, Details section:
    https://cran.r-project.org/web/packages/logistf/refman/logistf.html
    """
    if not isinstance(max_iter, int) or max_iter < 1:
        raise ValueError('max_iter must be a positive integer.')
    if not np.isfinite(tol) or tol <= 0 or not np.isfinite(max_step) or max_step <= 0:
        raise ValueError('tol and max_step must be finite and positive.')
    if not isinstance(max_halvings, int) or max_halvings < 0:
        raise ValueError('max_halvings must be a non-negative integer.')
    if 'outcome' not in d:
        raise ValueError('An outcome column is required.')
    y = d['outcome'].to_numpy(dtype=float)
    if len(y) < 3 or not np.isfinite(y).all() or not np.isin(y, [0, 1]).all():
        raise ValueError('Use at least three rows with finite binary outcomes.')
    if 'confidence' in d:
        scores = d['confidence'].to_numpy(dtype=float)
        if not np.isfinite(scores).all() or ((scores < 0) | (scores > 1)).any():
            raise ValueError('confidence must be finite and within [0, 1].')
        x = to_logit(scores)
    elif 'logit' in d:
        x = d['logit'].to_numpy(dtype=float)
    else:
        raise ValueError('A confidence or logit column is required.')
    if not np.isfinite(x).all():
        raise ValueError('Transformed scores must be finite.')
    center, scale = float(x.mean()), float(x.std())
    if not np.isfinite(scale) or scale <= np.finfo(float).eps * max(1.0, abs(center)):
        raise ValueError('Constant scores cannot identify intercept and slope.')
    X = np.column_stack([np.ones(len(y)), (x - center) / scale])
    if np.linalg.matrix_rank(X) != 2:
        raise ValueError('The intercept and score design must have full rank.')

    def evaluate(b):
        eta = X @ b
        p = expit(eta)
        # expit(-eta) avoids subtraction cancellation at high probabilities.
        w = p * expit(-eta)
        information = X.T @ (X * w[:, None])
        sign, logdet = np.linalg.slogdet(information)
        if sign <= 0 or not np.isfinite(logdet):
            raise np.linalg.LinAlgError('Non-positive Fisher information.')
        h = w * np.einsum('ij,ji->i', X, np.linalg.solve(information, X.T))
        score = X.T @ (y - p + h * (0.5 - p))
        objective = float(np.sum(y * eta - np.logaddexp(0.0, eta)) + 0.5 * logdet)
        if not np.isfinite(objective) or not np.isfinite(score).all():
            raise np.linalg.LinAlgError('Non-finite penalized likelihood or score.')
        return objective, score, information

    b = np.zeros(2)
    status, iteration, score_norm, objective = 'max_iterations', 0, np.nan, np.nan
    try:
        for iteration in range(1, max_iter + 1):
            objective, score, information = evaluate(b)
            score_norm = float(np.max(np.abs(score)))
            step = np.linalg.solve(information, score)
            if score_norm <= tol and np.max(np.abs(step)) <= tol:
                status = 'converged'
                break
            step /= max(1.0, float(np.max(np.abs(step))) / max_step)
            for _ in range(max_halvings + 1):
                candidate = b + step
                try:
                    candidate_objective, _, _ = evaluate(candidate)
                except np.linalg.LinAlgError:
                    candidate_objective = -np.inf
                if candidate_objective >= objective - 1e-12 * (1.0 + abs(objective)):
                    b = candidate
                    break
                step *= 0.5
            else:
                status = 'step_halving_failed'
                break
        objective, score, information = evaluate(b)
        score_norm = float(np.max(np.abs(score)))
        if status == 'max_iterations' and score_norm <= tol and np.max(np.abs(np.linalg.solve(information, score))) <= tol:
            status = 'converged'
    except np.linalg.LinAlgError:
        status = 'numerical_failure'
    converged = status == 'converged'
    return {'b0': float(b[0] - b[1] * center / scale) if converged else np.nan,
            'b1': float(b[1] / scale) if converged else np.nan,
            'converged': converged, 'fit_status': status, 'iterations': iteration,
            'max_abs_modified_score': score_norm, 'penalized_loglik_standardized': objective}


def firth_sensitivity(validation, predictions, target_p=TARGET_P, **fit_options):
    """Export estimator diagnostics without replacing the ordinary GLM policy."""
    if not np.isfinite(target_p) or not 0 < target_p < 1:
        raise ValueError('target_p must be strictly between zero and one.')
    rows = []
    for species, d in validation.groupby('commonName'):
        fit = fit_firth(d, **fit_options)
        logit_cut = threshold(fit['b0'], fit['b1'], target_p) if fit['converged'] else np.nan
        cut = from_logit(logit_cut)
        species_scores = predictions.loc[predictions['common_name'] == species, 'confidence']
        count = int((to_logit(species_scores) >= logit_cut).sum()) if np.isfinite(logit_cut) else 0
        status = ('not_converged' if not fit['converged'] else
                  'no_increasing_cutoff' if not np.isfinite(logit_cut) else
                  'sensitivity_only')
        rows.append({'species': species, 'firth_b0': fit['b0'], 'firth_b1': fit['b1'],
                     'firth_conf_threshold': cut, 'firth_candidates': count,
                     'firth_converged': fit['converged'], 'firth_fit_status': fit['fit_status'],
                     'firth_iterations': fit['iterations'],
                     'firth_max_abs_modified_score': fit['max_abs_modified_score'],
                     'firth_threshold_status': status, 'target_p': target_p,
                     'used_for_observation_labels': False})
    return pd.DataFrame(rows).set_index('species')




def fit_species_models(validation, predictions, species_order=None):
    """Fit outcome ~ logit(score), returning estimates and diagnostics by species."""
    rows=[]
    species_order=species_order or sorted(validation['commonName'].unique())
    for species in species_order:
        d=validation[validation['commonName']==species].copy()
        d['logit']=to_logit(d['confidence'])
        row={'species':species, **fit_glm(d)}
        row['logit_threshold']=threshold(row.get('b0'),row.get('b1'))
        row['conf_threshold']=from_logit(row['logit_threshold'])
        row['threshold_within_val_range']=bool(d['logit'].min()<=row['logit_threshold']<=d['logit'].max())
        row['n_preds_above']=int((to_logit(predictions.loc[predictions.common_name==species,'confidence'])>=row['logit_threshold']).sum())
        rows.append(row)
    return pd.DataFrame(rows).set_index('species')

def apply_support_policy(models, validation):
    """Withhold sparse-error and unsupported fits; no p-value-only acceptance rule."""
    result=models.copy()
    result['validation_score_min']=result.index.map(validation.groupby('commonName')['confidence'].min())
    result['validation_score_max']=result.index.map(validation.groupby('commonName')['confidence'].max())
    result['n_wrong']=result['n']-result['n_correct']
    result['method']='binomial_glm_logit_score'
    result['status']='unsupported_fit'
    for species,row in result.iterrows():
        valid_fit=row.get('fit_status')=='ok' and bool(row.get('converged',False)) and row.get('b1',0)>0
        if not valid_fit: continue
        if not row['threshold_within_val_range']:
            status='unsupported_target_outside_validation_range'
        elif row['n_wrong']<5:
            status='pending_review_sparse_errors'
        else:
            status='supported_exploratory_fit'
        result.loc[species,'status']=status
    # Five errors is a transparent screening heuristic, not evidence of guaranteed reliability.
    result['use_for_labels']=result['status'].eq('supported_exploratory_fit')
    result['target_p']=TARGET_P; result['eps']=EPS
    result['sensitivity_assumed']=SENSITIVITY
    result['model_version']=MODEL_VERSION; result['policy_version']=POLICY_VERSION
    return result

def label_predictions(predictions, registry):
    """Preserve rows; distinguish fitted candidates from policy-accepted observations."""
    labelled=predictions.drop(columns=['conf_bin'],errors='ignore').copy()
    labelled['logit']=to_logit(labelled['confidence'])
    labelled['model_status']=labelled['common_name'].map(registry['status']).fillna('unknown_species')
    labelled['conf_threshold']=labelled['common_name'].map(registry['conf_threshold'])
    labelled['p_correct']=np.nan
    for species,row in registry.iterrows():
        if row.get('fit_status')!='ok' or not bool(row.get('converged',False)):
            continue
        mask=labelled['common_name']==species
        labelled.loc[mask,'p_correct']=from_logit(row['b0']+row['b1']*labelled.loc[mask,'logit'])
    candidate=labelled['p_correct'].ge(TARGET_P)
    eligible=labelled['common_name'].map(registry['use_for_labels']).fillna(False)
    labelled['candidate_observation']=np.where(candidate,labelled['common_name'],'unconfirmed')
    labelled['observation']=np.where(candidate & eligible,labelled['common_name'],'unconfirmed')
    labelled['score_outside_validation_range']=(
        (labelled.confidence<labelled.common_name.map(registry.validation_score_min)) |
        (labelled.confidence>labelled.common_name.map(registry.validation_score_max)))
    labelled['needs_model_review']=~eligible | labelled['score_outside_validation_range']
    labelled['observation_source']='species_glm_policy'
    labelled['model_version']=MODEL_VERSION; labelled['policy_version']=POLICY_VERSION
    assert len(labelled)==len(predictions)
    accepted=labelled.observation.ne('unconfirmed')
    assert labelled.loc[accepted,'p_correct'].ge(TARGET_P).all()
    assert eligible[accepted].all()
    return labelled

def checked_cutoff_evidence(validation, registry):
    """Exact lower bounds describe checked data, not independent certification."""
    rows=[]
    for species,d in validation.groupby('commonName'):
        cutoff=registry.loc[species,'conf_threshold']
        retained=d[d.confidence>=cutoff] if np.isfinite(cutoff) else d
        k=int(retained.outcome.sum()); n=len(retained)
        lower=beta.ppf(.05,k,n-k+1) if k>0 else (0.0 if n else np.nan)
        rows.append({'species':species,'evaluation_scope':'at_fitted_cutoff' if np.isfinite(cutoff) else 'all_checked_scores',
                     'cutoff':cutoff,'checked':n,'correct':k,'precision':k/n if n else np.nan,
                     'one_sided_95_lower':lower,'use_for_labels':bool(registry.loc[species,'use_for_labels'])})
    return pd.DataFrame(rows)

def bin_weighted_precision(validation, predictions):
    """Reweight score bins only under stated within-bin representativeness assumptions."""
    bins=np.round(np.arange(.1,1.01,.1),1)
    summaries=[]; details=[]
    for species,d in validation.groupby('commonName'):
        checked=d.assign(bin=pd.cut(d.confidence,bins,include_lowest=True))
        tab=checked.groupby('bin',observed=False).outcome.agg(['mean','size'])
        pred=predictions[predictions.common_name==species]
        mass=pred.assign(bin=pd.cut(pred.confidence,bins,include_lowest=True)).groupby('bin',observed=False).size()
        assert int(mass.sum())==len(pred), 'Predictions fall outside the configured score bins.'
        tab['prediction_count']=mass;tab['weight']=mass/len(pred)
        supported=tab['size']>0
        covered=float(np.clip(tab.loc[supported,'weight'].sum(),0,1))
        contribution=float(np.clip((tab['weight']*tab['mean']).sum(),0,covered))
        summaries.append({'species':species,'checked_sample_precision':d.outcome.mean(),
                          'covered_prediction_share':min(1.0,covered),
                          'weighted_estimate_covered_bins':contribution/covered if covered else np.nan,
                          'uncovered_prediction_share':max(0.0,1-covered),
                          'missing_bin_scenario_low':contribution,'missing_bin_scenario_high':min(1.0,contribution+1-covered)})
        tab=tab.reset_index();tab.insert(0,'species',species);details.append(tab)
    return pd.DataFrame(summaries),pd.concat(details,ignore_index=True)
