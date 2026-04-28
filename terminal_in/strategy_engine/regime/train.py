"""
Offline HMM training script — run once after accumulating enough historical data.

Usage:
    python -m terminal_in.strategy_engine.regime.train --days 500

Trains a 6-state GaussianHMM on Nifty daily features and saves hmm_model.pkl
next to this file so RegimeClassifier can load it at runtime.
"""

import argparse
import logging
import os
import pickle

import numpy as np

log = logging.getLogger(__name__)

N_STATES = 6
STATE_NAMES = ['strong_bull', 'bull', 'sideways', 'bear', 'strong_bear', 'high_vol']
MODEL_PATH = os.path.join(os.path.dirname(__file__), 'hmm_model.pkl')


def _assign_state_names(model, features: np.ndarray) -> dict[int, str]:
    """
    Map HMM hidden states to human-readable names by inspecting emission means.
    Heuristic: sort by mean return component, then tag high-vol separately.
    """
    means = model.means_  # (n_states, n_features)
    # feature[0] = 5d return, feature[1] = 20d vol, feature[2] = ema_ratio, feature[3] = vix_norm
    ret_col = means[:, 0]
    vol_col = means[:, 1]

    order = np.argsort(ret_col)  # ascending by return
    mapping = {}
    # high_vol: highest vol state (regardless of return)
    hv_idx = int(np.argmax(vol_col))
    mapping[hv_idx] = 'high_vol'

    remaining = [i for i in range(N_STATES) if i != hv_idx]
    remaining_sorted = sorted(remaining, key=lambda i: ret_col[i])

    labels = ['strong_bear', 'bear', 'sideways', 'bull', 'strong_bull']
    # handle fewer remaining states than labels
    for rank, idx in enumerate(remaining_sorted):
        label_idx = int(round(rank * (len(labels) - 1) / max(len(remaining_sorted) - 1, 1)))
        mapping[idx] = labels[label_idx]

    return mapping


def train(db, days: int = 500):
    """
    Pull Nifty 1d OHLCV + VIX from DB, build features, train HMM, save model.
    """
    try:
        from hmmlearn import hmm
    except ImportError:
        log.error('hmmlearn not installed — run: pip install hmmlearn')
        return

    from terminal_in.strategy_engine.regime.classifier import _extract_features

    nifty_df = db.get_ohlcv_1d(token=256265, limit=days)
    vix_df = db.get_ohlcv_1d(token=264969, limit=days)  # India VIX token

    if nifty_df.empty or len(nifty_df) < 60:
        log.error('Not enough Nifty data for training (%d rows)', len(nifty_df))
        return

    close = nifty_df['close'].values.astype(float)
    if vix_df.empty or len(vix_df) < len(close):
        vix_arr = np.full(len(close), 15.0)
    else:
        vix_arr = vix_df['close'].values.astype(float)[-len(close):]

    features = _extract_features(close, vix_arr)
    valid_mask = ~np.isnan(features).any(axis=1)
    feat_clean = features[valid_mask]

    if len(feat_clean) < 50:
        log.error('Insufficient clean features (%d rows) after NA removal', len(feat_clean))
        return

    log.info('Training HMM on %d samples, %d features', len(feat_clean), feat_clean.shape[1])

    model = hmm.GaussianHMM(
        n_components=N_STATES,
        covariance_type='full',
        n_iter=200,
        tol=1e-4,
        random_state=42,
        verbose=False,
    )
    model.fit(feat_clean, lengths=[len(feat_clean)])
    log.info('HMM training complete. Score: %.4f', model.score(feat_clean))

    model.state_map = _assign_state_names(model, feat_clean)
    log.info('State assignments: %s', model.state_map)

    with open(MODEL_PATH, 'wb') as f:
        pickle.dump(model, f, protocol=pickle.HIGHEST_PROTOCOL)
    log.info('Model saved to %s', MODEL_PATH)
    return model


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description='Train HMM regime classifier')
    parser.add_argument('--days', type=int, default=500, help='Days of history to train on')
    args = parser.parse_args()

    from terminal_in.db import DB
    db = DB()
    train(db, days=args.days)
