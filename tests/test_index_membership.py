"""Research universe + point-in-time index membership (survivorship-correct query)."""

from terminal_in.data_ingest import index_membership as IM
from terminal_in.data_ingest.instruments import KNOWN_TOKENS


def test_members_as_of_point_in_time_semantics(monkeypatch):
    # inject a membership history with a name removed and one added later
    monkeypatch.setattr(IM, '_MEMBERSHIP', {'TESTIDX': [
        ('ALWAYS',  '2016-01-01', None),          # member throughout
        ('REMOVED', '2016-01-01', '2020-06-01'),  # left mid-2020
        ('ADDED',   '2021-01-01', None),          # joined 2021
    ]})
    assert IM.members_as_of('TESTIDX', '2018-01-01') == {'ALWAYS', 'REMOVED'}
    assert IM.members_as_of('TESTIDX', '2020-07-01') == {'ALWAYS'}              # REMOVED gone
    assert IM.members_as_of('TESTIDX', '2022-01-01') == {'ALWAYS', 'ADDED'}    # ADDED in
    # case-insensitive index name
    assert IM.members_as_of('testidx', '2018-01-01') == {'ALWAYS', 'REMOVED'}


def test_seed_is_current_snapshot_all_present_now():
    names = IM.members_as_of('NIFTY MIDCAP 150', '2026-06-18')
    assert names == set(IM.research_symbols())
    assert len(names) == len(IM.MIDCAP_SECTORS)


def test_coverage_flags_survivorship_uncorrected():
    c = IM.coverage()
    assert c['survivorship_corrected'] is False        # honest: snapshot only
    assert c['curated_names'] == len(IM.MIDCAP_SECTORS)
    assert c['official_full'] == 150


def test_research_tokens_band_and_no_live_collision():
    live_tokens = set(KNOWN_TOKENS.values())
    live_symbols = set(KNOWN_TOKENS)
    for sym, tok in IM.RESEARCH_TOKENS.items():
        assert tok >= 920_000_000                      # research band
        assert tok not in live_tokens                  # no token collision with live
        assert sym not in live_symbols                 # no duplicate ticker vs live 72
    # tokens are a stable bijection
    assert len(IM.RESEARCH_TOKENS) == len(set(IM.RESEARCH_TOKENS.values()))


def test_every_research_symbol_has_a_sector():
    assert all(IM.sector_of(s) != 'other' for s in IM.research_symbols())


def _isolate(monkeypatch):
    """Sandbox the mutable module globals so reconstitution-loading tests don't leak."""
    monkeypatch.setattr(IM, 'MIDCAP_SECTORS', dict(IM.MIDCAP_SECTORS))
    monkeypatch.setattr(IM, 'RESEARCH_TOKENS', dict(IM.RESEARCH_TOKENS))
    monkeypatch.setattr(IM, 'RESEARCH_BY_TOKEN', dict(IM.RESEARCH_BY_TOKEN))
    monkeypatch.setattr(IM, '_MEMBERSHIP', {k: list(v) for k, v in IM._MEMBERSHIP.items()})
    monkeypatch.setattr(IM, 'SURVIVORSHIP_CORRECTED', False)


def test_load_reconstitution_makes_membership_pit_and_flips_flag(monkeypatch):
    _isolate(monkeypatch)
    res = IM.load_reconstitution([
        {'symbol': 'LUPIN', 'effective_from': '2016-01-01', 'effective_to': None},
        {'symbol': 'DELISTED1', 'effective_from': '2016-01-01', 'effective_to': '2019-05-01', 'sector': 'pharma'},
        {'symbol': 'bad', 'effective_from': 'not-a-date'},      # FAIL-CLOSED → dropped
        {'symbol': '', 'effective_from': '2016-01-01'},          # no symbol → dropped
    ])
    assert res['loaded'] == 2 and res['dropped_unverifiable'] == 2
    assert res['survivorship_corrected'] is True and IM.SURVIVORSHIP_CORRECTED is True
    # the delisted name is queryable point-in-time and correctly disappears after exit
    assert 'DELISTED1' in IM.members_as_of('NIFTY MIDCAP 150', '2018-01-01')
    assert 'DELISTED1' not in IM.members_as_of('NIFTY MIDCAP 150', '2020-01-01')
    # a newly-seen (delisted) symbol gets a stable in-band research token
    assert IM.RESEARCH_TOKENS['DELISTED1'] >= 920_000_000


def test_load_reconstitution_file_csv(tmp_path, monkeypatch):
    _isolate(monkeypatch)
    p = tmp_path / 'recon.csv'
    p.write_text('symbol,effective_from,effective_to,sector\n'
                 'LUPIN,2016-01-01,,pharma\n'
                 'OLDNAME,2016-01-01,2018-03-01,auto\n')
    res = IM.load_reconstitution_file(str(p))
    assert res['loaded'] == 2
    assert 'OLDNAME' in IM.members_as_of('NIFTY MIDCAP 150', '2017-01-01')
    assert 'OLDNAME' not in IM.members_as_of('NIFTY MIDCAP 150', '2019-01-01')
