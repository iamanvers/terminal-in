"""
Signal noise-reduction filters for the TradeOrchestrator.

Pure functions/classes — no bus or DB imports — so they are unit-testable.

Layers:
  1. data_quality()    — refuse to generate signals on thin or stale history
  2. CandidateTracker  — persistence/debounce + confidence EMA + EV hysteresis:
                         a setup must survive ≥2 consecutive scans, its smoothed
                         confidence must clear the floor, and EV must enter above
                         the high-water mark (and only de-activates below the
                         low-water mark) before it is eligible to fire.
"""

import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

MIN_DAILY_BARS    = 30      # minimum real daily bars before technicals mean anything
MAX_BAR_AGE_DAYS  = 7       # last daily bar older than this → stale (holiday-safe)
MAX_TICK_AGE_S    = 600     # live tick older than 10 min → stale price


def data_quality(df1d, live_price: float, tick_age_s: float | None = None) -> tuple[bool, str]:
    """
    Returns (ok, reason). reason is '' when ok.
    df1d: pandas DataFrame with DatetimeIndex (may be None/empty).
    """
    if df1d is None or df1d.empty:
        return False, 'no_ohlcv'
    if len(df1d) < MIN_DAILY_BARS:
        return False, f'thin_history({len(df1d)}<{MIN_DAILY_BARS})'

    try:
        import pandas as pd
        last_ts = df1d.index[-1]
        last_ts = last_ts.tz_localize(None) if getattr(last_ts, 'tzinfo', None) else last_ts
        age_days = (pd.Timestamp.now() - last_ts).days
        if age_days > MAX_BAR_AGE_DAYS:
            return False, f'stale_bars({age_days}d)'
    except Exception:
        pass  # unparseable index — don't block on the freshness check alone

    if live_price <= 0:
        return False, 'no_live_price'
    if tick_age_s is not None and tick_age_s > MAX_TICK_AGE_S:
        return False, f'stale_tick({int(tick_age_s)}s)'
    return True, ''


@dataclass
class _TrackState:
    streak: int = 0            # consecutive scans this (token, side) triggered
    conf_ema: float = 0.0
    active: bool = False       # EV hysteresis state
    last_seen: float = field(default_factory=time.monotonic)


class CandidateTracker:
    """
    Tracks candidate setups across scans, keyed by (token, side).

    update() annotates each candidate dict in place with:
      'persistence'    — consecutive scans this setup has triggered
      'conf_smoothed'  — EMA of confidence across scans
      'eligible'       — True only when persistence ≥ required AND smoothed
                         confidence ≥ min_conf AND EV hysteresis is active
      'filter_reason'  — why a non-eligible candidate was held back ('' if eligible)

    Entries absent from a scan reset their streak; entries unseen for
    expire_after_s are dropped entirely.
    """

    def __init__(self,
                 alpha: float = 0.4,
                 required_persistence: int = 2,
                 min_conf: float = 0.45,
                 ev_enter: float = 1.2,
                 ev_exit: float = 1.0,
                 expire_after_s: float = 1800.0):
        self._alpha    = alpha
        self._required = required_persistence
        self._min_conf = min_conf
        self._ev_enter = ev_enter
        self._ev_exit  = ev_exit
        self._expire_s = expire_after_s
        self._state: dict[tuple[int, str], _TrackState] = {}

    def update(self, candidates: list[dict], now: float | None = None) -> list[dict]:
        now = time.monotonic() if now is None else now
        seen: set[tuple[int, str]] = set()

        for c in candidates:
            side = c.get('side')
            if side in ('NEUTRAL', 'SKIP', None):
                continue
            key = (int(c.get('token', 0)), side)
            seen.add(key)

            st = self._state.get(key)
            if st is None:
                st = _TrackState()
                self._state[key] = st

            st.streak += 1
            st.last_seen = now
            conf = float(c.get('confidence', 0.0))
            st.conf_ema = conf if st.streak == 1 else (
                self._alpha * conf + (1 - self._alpha) * st.conf_ema
            )

            ev = float(c.get('ev', 0.0))
            if st.active:
                if ev < self._ev_exit:
                    st.active = False
            elif ev >= self._ev_enter:
                st.active = True

            c['persistence']   = st.streak
            c['conf_smoothed'] = round(st.conf_ema, 3)

            reasons = []
            if st.streak < self._required:
                reasons.append(f'persistence({st.streak}/{self._required})')
            if st.conf_ema < self._min_conf:
                reasons.append(f'conf_ema({st.conf_ema:.2f}<{self._min_conf})')
            if not st.active:
                reasons.append(f'ev_hysteresis(<{self._ev_enter})')
            c['eligible']      = not reasons
            c['filter_reason'] = '+'.join(reasons)

        # Reset streaks for setups that vanished this scan; expire old entries
        for key, st in list(self._state.items()):
            if key in seen:
                continue
            st.streak = 0
            st.active = False
            if now - st.last_seen > self._expire_s:
                del self._state[key]

        return candidates


class RegimeHysteresis:
    """A new regime's effect applies only after it holds N consecutive scans."""

    def __init__(self, required: int = 2):
        self._required  = required
        self._effective: str | None = None
        self._pending:   str | None = None
        self._count     = 0

    def update(self, observed: str) -> str:
        if self._effective is None:
            self._effective = observed
            return observed
        if observed == self._effective:
            self._pending = None
            self._count = 0
        elif observed == self._pending:
            self._count += 1
            if self._count >= self._required:
                self._effective = observed
                self._pending = None
                self._count = 0
        else:
            self._pending = observed
            self._count = 1
        return self._effective
