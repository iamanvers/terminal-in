"""
M1 — 6-state Gaussian HMM regime classifier.
States: strong_bull, bull, sideways, bear, strong_bear, high_vol.
Features: 5-day return, 20-day vol, 5/20 EMA ratio, India VIX normalised.
3-day hysteresis: state must persist 3 consecutive days before switching.
"""

import logging
import os
import pickle
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

N_STATES = 6
STATE_NAMES = ['strong_bull', 'bull', 'sideways', 'bear', 'strong_bear', 'high_vol']
HYSTERESIS_DAYS = 3
MODEL_PATH = os.path.join(os.path.dirname(__file__), 'hmm_model.pkl')

# Regime → size multiplier
SIZE_MULTIPLIERS = {
    'strong_bull': 1.2,
    'bull': 1.0,
    'sideways': 0.7,
    'bear': 0.5,
    'strong_bear': 0.3,
    'high_vol': 0.2,
}


def _extract_features(close: np.ndarray, vix: np.ndarray) -> np.ndarray:
    """Build feature matrix from price series and VIX. Returns (n, 4) array."""
    n = len(close)
    features = np.full((n, 4), np.nan)

    for i in range(20, n):
        ret_5 = (close[i] - close[i - 5]) / close[i - 5]
        vol_20 = float(np.std(np.diff(np.log(close[i - 20:i + 1]))))
        ema5 = float(np.mean(close[i - 5:i]))
        ema20 = float(np.mean(close[i - 20:i]))
        ema_ratio = ema5 / ema20 - 1.0
        vix_norm = float(vix[i]) / 20.0 - 1.0 if vix is not None and len(vix) > i else 0.0
        features[i] = [ret_5, vol_20, ema_ratio, vix_norm]

    return features


class RegimeClassifier:
    def __init__(self):
        self._model = None
        self._pending_state: Optional[str] = None
        self._pending_count: int = 0
        self._current_state: str = 'sideways'
        self._current_confidence: float = 0.5
        self._last_asof = None   # date of the last daily bar we classified on
        self._load_model()

    def _load_model(self):
        if os.path.exists(MODEL_PATH):
            try:
                with open(MODEL_PATH, 'rb') as f:
                    self._model = pickle.load(f)
                log.info('HMM model loaded from %s', MODEL_PATH)
            except Exception:
                log.warning('Failed to load HMM model — using heuristic fallback')
        else:
            log.info('No HMM model file found at %s — heuristic mode', MODEL_PATH)

    def classify(self, close: np.ndarray, vix: float, asof=None) -> tuple[str, float]:
        """
        Returns (regime_name, confidence).

        Regime is a DAILY concept. ``asof`` is the date of the latest daily bar;
        when it has not changed since the last classification we return the
        current state UNCHANGED — repeated intraday scans on the same settled bar
        must never flip the regime (the "bear↔sideways without new data" bug).
        Only a genuinely new daily bar advances the 3-day hysteresis, so the
        documented "3-day" persistence is now measured in trading days, not scans.
        """
        if asof is not None and asof == self._last_asof:
            return self._current_state, self._current_confidence
        self._last_asof = asof

        if self._model is not None:
            return self._classify_hmm(close, vix)
        return self._classify_heuristic(close, vix)

    def _classify_hmm(self, close: np.ndarray, vix: float) -> tuple[str, float]:
        try:
            vix_arr = np.full(len(close), vix)
            features = _extract_features(close, vix_arr)
            valid = ~np.isnan(features).any(axis=1)
            if valid.sum() < 5:
                return self._classify_heuristic(close, vix)

            feat_clean = features[valid]
            lengths = [len(feat_clean)]
            state_seq = self._model.predict(feat_clean, lengths)
            last_state_idx = int(state_seq[-1])

            posteriors = self._model.predict_proba(feat_clean, lengths)
            confidence = float(posteriors[-1, last_state_idx])

            # Map HMM state index → name (model stores mapping after training)
            if hasattr(self._model, 'state_map'):
                raw_name = self._model.state_map.get(last_state_idx, 'sideways')
            else:
                raw_name = STATE_NAMES[last_state_idx % N_STATES]

            return self._apply_hysteresis(raw_name, confidence)
        except Exception:
            log.exception('HMM classification failed — falling back to heuristic')
            return self._classify_heuristic(close, vix)

    def _classify_heuristic(self, close: np.ndarray, vix: float) -> tuple[str, float]:
        """Rule-based fallback when no model is trained yet."""
        if len(close) < 21:
            return 'sideways', 0.5

        log_rets = np.diff(np.log(close[-21:]))
        # Drop outlier bars (> 12% daily = corrupted/holiday data crossover)
        clean_rets = log_rets[np.abs(log_rets) < 0.12]
        if len(clean_rets) < 8:
            clean_rets = log_rets  # fallback if too much filtered
        vol = float(np.std(clean_rets))
        ann_vol = vol * np.sqrt(252)

        # Use trimmed 20d return: pick last close vs close 20 trading days ago,
        # but skip outlier seed bars (filter bars with realistic prices only)
        valid_close = close[np.isfinite(close)]
        ret_20 = (valid_close[-1] - valid_close[-20]) / valid_close[-20] if len(valid_close) >= 20 else 0.0

        # Clamp ret_20 to realistic range for Indian large-caps
        ret_20 = max(-0.25, min(0.25, ret_20))

        if vix > 25 or ann_vol > 0.40:
            raw = 'high_vol'
        elif ret_20 > 0.06:
            raw = 'strong_bull'
        elif ret_20 > 0.02:
            raw = 'bull'
        elif ret_20 < -0.06:
            raw = 'strong_bear'
        elif ret_20 < -0.02:
            raw = 'bear'
        else:
            raw = 'sideways'

        confidence = 0.55 + min(abs(ret_20) * 3, 0.30)
        return self._apply_hysteresis(raw, confidence)

    def _apply_hysteresis(self, candidate: str, confidence: float) -> tuple[str, float]:
        if candidate == self._current_state:
            self._pending_state = None
            self._pending_count = 0
            self._current_confidence = confidence
            return self._current_state, confidence

        if candidate == self._pending_state:
            self._pending_count += 1
        else:
            self._pending_state = candidate
            self._pending_count = 1

        if self._pending_count >= HYSTERESIS_DAYS:
            self._current_state = candidate
            self._current_confidence = confidence
            self._pending_state = None
            self._pending_count = 0

        return self._current_state, self._current_confidence

    @property
    def current_state(self) -> str:
        return self._current_state

    @property
    def size_multiplier(self) -> float:
        return SIZE_MULTIPLIERS.get(self._current_state, 1.0)

    @property
    def mode(self) -> str:
        """'hmm' when the trained model is active, 'heuristic' otherwise."""
        return 'hmm' if self._model is not None else 'heuristic'


classifier = RegimeClassifier()
