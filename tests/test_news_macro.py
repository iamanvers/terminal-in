"""India-context macro sentiment priors (terminal_in/news/macro.py).

Locks in the well-established broad-market relationships FinBERT gets backwards —
notably the two real misreads the owner reported: a rising dollar-vs-rupee scored
positive, and a fuel-price drop scored negative.
"""

import pytest

from terminal_in.news import macro


def _sent(text):
    r = macro.adjust(text)
    return r['sentiment'] if r else None


# ── the two reported misreads ────────────────────────────────────────────────
def test_rupee_depreciation_is_negative():
    assert _sent('Rupee falls to record low against the US dollar') == 'negative'
    assert _sent('Dollar strengthens against the rupee, USD/INR rises') == 'negative'
    assert _sent('Dollar vs rupee increases as greenback gains') == 'negative'


def test_fuel_price_drop_is_positive():
    assert _sent('Petrol and diesel prices drop sharply across metros') == 'positive'
    assert _sent('Brent crude oil falls below $70 a barrel') == 'positive'


# ── the inverse moves ────────────────────────────────────────────────────────
def test_rupee_appreciation_is_positive():
    assert _sent('Rupee strengthens, gains against the dollar') == 'positive'
    assert _sent('Dollar weakens against the rupee') == 'positive'


def test_crude_up_is_negative():
    assert _sent('Crude oil prices surge on supply cuts') == 'negative'
    assert _sent('Petrol prices hiked, fuel costs rise') == 'negative'


# ── other locked-in relationships ────────────────────────────────────────────
def test_inflation_direction():
    assert _sent('India CPI inflation rises to 6.5% in May') == 'negative'
    assert _sent('Retail inflation eases, CPI cools to 4%') == 'positive'


def test_rbi_rate_action():
    assert _sent('RBI cuts repo rate by 25 bps') == 'positive'
    assert _sent('RBI hikes repo rate to tame inflation') == 'negative'


def test_fii_flows():
    assert _sent('FIIs pour money into Indian equities, strong inflows') == 'positive'
    assert _sent('FPIs sell Indian shares, heavy outflows continue') == 'negative'


def test_growth_and_gst_positive_when_up():
    assert _sent('India GDP growth accelerates to 7.8%') == 'positive'
    assert _sent('GST collections rise to record high in April') == 'positive'


def test_deficit_widening_negative():
    assert _sent('India trade deficit widens sharply in March') == 'negative'


def test_monsoon():
    assert _sent('Monsoon normal this year, IMD forecasts good rains') == 'positive'
    assert _sent('Monsoon deficient, rainfall below normal') == 'negative'


def test_non_macro_headline_returns_none():
    # company-specific news has no macro override → FinBERT decides
    assert macro.adjust('Reliance Q4 net profit rises 12% on retail strength') is None
    assert macro.adjust('TCS wins large deal from European bank') is None
    assert macro.adjust('') is None


def test_score_flags_override_transparently():
    """sentiment.score must expose macro_rule + the original finbert call when it
    overrides, and leave normal company news to FinBERT (no macro_rule key)."""
    from terminal_in.news import sentiment
    r = sentiment.score('Rupee hits record low as dollar surges')
    assert r['sentiment'] == 'negative' and r['macro_rule'] == 'rupee_depreciation'
    assert 'finbert' in r                                  # transparency: what FinBERT said
    r2 = sentiment.score('Acme Corp announces new product')
    assert 'macro_rule' not in r2                          # untouched by the macro layer
