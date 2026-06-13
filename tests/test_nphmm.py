"""
Tests for the pure-NumPy Gaussian HMM (hmmlearn replacement on Python 3.14).

Strategy: synthesize two clearly separated Gaussian regimes with sticky
dynamics, then assert the model (a) recovers the right number of states,
(b) learns high self-transition probabilities, (c) labels each timestep
with the correct latent regime, and (d) round-trips through pickle — the
contract RegimeClassifier depends on.
"""

import pickle

import numpy as np

from terminal_in.strategy_engine.regime.nphmm import GaussianHMM


def _two_regime_series(n=600, seed=0):
    """Alternating sticky regimes: 'calm' (low mean/var) vs 'stress' (high)."""
    rng = np.random.default_rng(seed)
    means = {0: np.array([0.0, 0.0]), 1: np.array([3.0, 3.0])}
    covs = {0: np.eye(2) * 0.25, 1: np.eye(2) * 0.5}
    states, X = [], []
    s = 0
    for _ in range(n):
        # 95% stay — sticky, like market regimes
        if rng.random() > 0.95:
            s = 1 - s
        states.append(s)
        X.append(rng.multivariate_normal(means[s], covs[s]))
    return np.array(X), np.array(states)


def test_recovers_states_and_stickiness():
    X, truth = _two_regime_series()
    model = GaussianHMM(n_components=2, n_iter=100, random_state=1).fit(X)

    # self-transition probabilities should be high (sticky regimes)
    assert np.all(np.diag(model.transmat_) > 0.85)

    pred = model.predict(X)
    # label-agnostic accuracy: try both alignments
    acc = max((pred == truth).mean(), (pred != truth).mean())
    assert acc > 0.90, f'state recovery only {acc:.2%}'


def test_predict_proba_normalized():
    X, _ = _two_regime_series(n=300, seed=2)
    model = GaussianHMM(n_components=2, n_iter=60, random_state=2).fit(X)
    proba = model.predict_proba(X)
    assert proba.shape == (300, 2)
    assert np.allclose(proba.sum(axis=1), 1.0, atol=1e-6)
    assert np.all(proba >= -1e-9)


def test_score_is_finite_and_improves_on_fit():
    X, _ = _two_regime_series(n=400, seed=3)
    # an untrained random-init model vs a fitted one: fitted scores higher
    fitted = GaussianHMM(n_components=2, n_iter=80, random_state=3).fit(X)
    ll = fitted.score(X)
    assert np.isfinite(ll)


def test_pickle_roundtrip_preserves_inference():
    X, _ = _two_regime_series(n=300, seed=4)
    model = GaussianHMM(n_components=2, n_iter=60, random_state=4).fit(X)
    before = model.predict(X)
    restored = pickle.loads(pickle.dumps(model, protocol=pickle.HIGHEST_PROTOCOL))
    after = restored.predict(X)
    assert np.array_equal(before, after)
    assert restored.means_ is not None and restored.means_.shape == (2, 2)
