"""
EventCalendar — loads high-impact event dates and computes event_mask.
0.0 = full blackout (within 1 day of event), 1.0 = fully open.
Covers: RBI MPC, Budget, NSE expiry Thursdays, US Fed FOMC.
"""

import logging
from datetime import date, timedelta
from typing import Optional

log = logging.getLogger(__name__)

# Static high-impact events for FY2025-26 (update annually)
# Format: (year, month, day, event_name, mask_value_on_day)
_STATIC_EVENTS: list[tuple[int, int, int, str, float]] = [
    # RBI MPC meetings (typically 6 per year, ~every 2 months)
    (2025, 4, 9, 'RBI MPC', 0.3),
    (2025, 6, 6, 'RBI MPC', 0.3),
    (2025, 8, 8, 'RBI MPC', 0.3),
    (2025, 10, 8, 'RBI MPC', 0.3),
    (2025, 12, 6, 'RBI MPC', 0.3),
    (2026, 2, 7, 'RBI MPC', 0.3),
    # Union Budget
    (2026, 2, 1, 'Union Budget', 0.0),
    # US FOMC (approximate — 8 per year)
    (2025, 5, 7, 'FOMC', 0.5),
    (2025, 6, 18, 'FOMC', 0.5),
    (2025, 7, 30, 'FOMC', 0.5),
    (2025, 9, 17, 'FOMC', 0.5),
    (2025, 11, 7, 'FOMC', 0.5),
    (2025, 12, 10, 'FOMC', 0.5),
    (2026, 1, 29, 'FOMC', 0.5),
    (2026, 3, 19, 'FOMC', 0.5),
]

# NSE F&O expiry — last Thursday of each month (generated dynamically)


def _last_thursday(year: int, month: int) -> date:
    # Find last Thursday of the month
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    d = date(year, month, last_day)
    while d.weekday() != 3:  # 3 = Thursday
        d -= timedelta(days=1)
    return d


def _build_expiry_events(start_year: int, end_year: int) -> list[tuple[date, str, float]]:
    events = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            expiry = _last_thursday(year, month)
            events.append((expiry, 'NSE F&O Expiry', 0.5))
    return events


class EventCalendar:
    def __init__(self):
        self._events: list[tuple[date, str, float]] = []
        self._load()

    def _load(self):
        today = date.today()
        for y, m, d, name, mask in _STATIC_EVENTS:
            self._events.append((date(y, m, d), name, mask))

        expiries = _build_expiry_events(today.year - 1, today.year + 2)
        self._events.extend(expiries)

        log.info('EventCalendar loaded %d events', len(self._events))

    def mask(self, today: Optional[date] = None) -> float:
        """
        Returns event_mask for today (and adjacent days).
        1.0 = no event; lower = more restricted.
        """
        if today is None:
            today = date.today()

        min_mask = 1.0
        for event_date, name, event_mask in self._events:
            delta = abs((event_date - today).days)
            if delta == 0:
                min_mask = min(min_mask, event_mask)
            elif delta == 1:
                # Day before/after: partial restriction
                min_mask = min(min_mask, (1.0 + event_mask) / 2.0)

        return min_mask

    def upcoming(self, today: Optional[date] = None, days: int = 14) -> list[dict]:
        if today is None:
            today = date.today()
        end = today + timedelta(days=days)
        return [
            {'date': str(d), 'event': name, 'mask': mask}
            for d, name, mask in sorted(self._events, key=lambda x: x[0])
            if today <= d <= end
        ]


calendar = EventCalendar()
