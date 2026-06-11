"""
NSE market-hours discipline — the single source of truth for "is the market
trading right now". Signals may be COMPUTED any time (for display), but
nothing may FIRE, FILL, or EXIT outside real trading hours: paper fills at
a stale last-close price at midnight are noise, not simulation.
"""

from datetime import datetime, time as dtime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

OPEN_T  = dtime(9, 15)
CLOSE_T = dtime(15, 30)

# 2026 NSE trading holidays (weekday ones). Update yearly.
HOLIDAYS_2026 = {
    '2026-01-26', '2026-02-17', '2026-03-03', '2026-03-21', '2026-04-03',
    '2026-04-14', '2026-05-01', '2026-08-15', '2026-09-14', '2026-10-02',
    '2026-10-20', '2026-11-09', '2026-12-25',
}


def now_ist() -> datetime:
    return datetime.now(IST)


def is_market_open(at: datetime | None = None) -> bool:
    """True only during the real NSE cash session (Mon–Fri 09:15–15:30 IST,
    excluding listed holidays)."""
    dt = at or now_ist()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    dt = dt.astimezone(IST)
    if dt.weekday() >= 5:
        return False
    if dt.strftime('%Y-%m-%d') in HOLIDAYS_2026:
        return False
    return OPEN_T <= dt.time() <= CLOSE_T
