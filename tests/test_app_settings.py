"""Operator settings (PRD 5b.2): validation, persistence, precedence."""

import os

import pytest

from terminal_in import app_settings
from terminal_in.db import DB


@pytest.fixture
def db(tmp_path):
    return DB(tmp_path / 'test.db')


def test_set_and_get_roundtrip(db):
    app_settings.update(db, {'REPORT_EMAIL_TO': 'ops@example.com'})
    assert db.get_app_settings()['REPORT_EMAIL_TO'] == 'ops@example.com'
    assert app_settings.current_values(db)['REPORT_EMAIL_TO'] == 'ops@example.com'


def test_unknown_key_rejected(db):
    with pytest.raises(ValueError, match='unknown setting'):
        app_settings.update(db, {'NOT_A_SETTING': '1'})


def test_number_range_enforced(db):
    with pytest.raises(ValueError, match='below minimum'):
        app_settings.update(db, {'INITIAL_CAPITAL': '5'})
    with pytest.raises(ValueError, match='above maximum'):
        app_settings.update(db, {'MAX_DD_PCT': '0.9'})


def test_select_options_enforced(db):
    with pytest.raises(ValueError, match='must be one of'):
        app_settings.update(db, {'MODE': 'turbo'})
    app_settings.update(db, {'MODE': 'live'})  # valid


def test_bool_validation(db):
    with pytest.raises(ValueError, match='expected true/false'):
        app_settings.update(db, {'PLANNER_ENABLED': 'maybe'})


def test_hot_vs_restart_classification(db):
    r = app_settings.update(db, {'LOG_LEVEL': 'DEBUG', 'MODE': 'paper'})
    assert 'LOG_LEVEL' in r['applied']
    assert 'MODE' in r['restart_required']


def test_masked_secret_not_clobbered(db):
    app_settings.update(db, {'SMTP_PASS': 'real-secret'})
    # the UI re-posts the mask when the field was untouched
    app_settings.update(db, {'SMTP_PASS': '••••••••'})
    assert db.get_app_settings()['SMTP_PASS'] == 'real-secret'


def test_secrets_masked_in_describe(db):
    app_settings.update(db, {'SMTP_PASS': 'real-secret'})
    item = next(s for s in app_settings.describe(db) if s['env'] == 'SMTP_PASS')
    assert item['value'] == '••••••••'
    assert 'real-secret' not in str(item)


def test_apply_overrides_pushes_env(db, monkeypatch):
    monkeypatch.delenv('REPORT_EMAIL_TO', raising=False)
    app_settings.update(db, {'REPORT_EMAIL_TO': 'boot@example.com'})
    n = app_settings.apply_overrides(db)
    assert n >= 1
    assert os.environ['REPORT_EMAIL_TO'] == 'boot@example.com'


def test_override_beats_env(db, monkeypatch):
    monkeypatch.setenv('OLLAMA_MODEL', 'env-model')
    assert app_settings.current_values(db)['OLLAMA_MODEL'] == 'env-model'
    app_settings.update(db, {'OLLAMA_MODEL': 'db-model'})
    assert app_settings.current_values(db)['OLLAMA_MODEL'] == 'db-model'
