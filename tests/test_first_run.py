"""First-run onboarding wizard — pure mapping + marker logic (PRD 5b.1)."""

import importlib.util
from pathlib import Path

import pytest

# packaging/ is not an importable package; load first_run by path.
_FR = Path(__file__).resolve().parents[1] / 'packaging' / 'first_run.py'
_spec = importlib.util.spec_from_file_location('first_run', _FR)
first_run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(first_run)


def test_build_changes_maps_capital_and_tier():
    c = first_run.build_changes({'capital': '500000', 'tier': 'balanced', 'mode': 'paper'})
    assert c['INITIAL_CAPITAL'] == '500000'
    assert c['MAX_DD_PCT'] == '0.15' and c['DAILY_LOSS_CAP_PCT'] == '0.03'
    assert c['MODE'] == 'paper'
    # no optional secrets supplied → not persisted
    assert 'KITE_API_KEY' not in c


def test_build_changes_aggressive_default_and_live_keys():
    c = first_run.build_changes({'mode': 'live', 'kite_key': 'abc', 'kite_token': 'tok',
                                 'smtp_pass': '  '})  # blank ignored
    assert c['MODE'] == 'live'
    assert c['MAX_DD_PCT'] == '0.20'                 # aggressive default tier
    assert c['KITE_API_KEY'] == 'abc' and c['KITE_ACCESS_TOKEN'] == 'tok'
    assert 'SMTP_PASS' not in c                       # whitespace-only dropped


def test_build_changes_floors_capital_and_handles_garbage():
    assert first_run.build_changes({'capital': '50'})['INITIAL_CAPITAL'] == '10000'
    assert first_run.build_changes({'capital': 'oops'})['INITIAL_CAPITAL'] == '1000000'


def test_onboarding_marker_roundtrip(tmp_path):
    assert first_run.needs_onboarding(tmp_path) is True
    first_run.mark_done(tmp_path)
    assert first_run.needs_onboarding(tmp_path) is False
