"""Offline regressions for real source schemas; all prices are synthetic."""
from pathlib import Path
from types import SimpleNamespace
import json
import sys

import pandas as pd
import pytest

import api
import api_store
import run_integrated as run
from normalize import Deal, ct_row_to_deal, myp_row_to_deal, read_ct
from cross_source import canonical_set_of, group_cross_source
from delivery import build_markdown, bucket_for, SourceStatus
from set_registry import resolve_scope, to_ct_sets, to_myp_editions


def ct_row(**changes):
    row = {'Card Name': 'Eevee', 'Set': 'Prismatic Evolutions (pre)', 'Nº': '074',
           'TCG Market (BRL)': 200, 'TCG Market (USD)': 40, 'Scan R$ (raw)': 100,
           'Variant': 'reverseHolofoil', 'Variante Baixa Confiança': 'Sim',
           'Fonte Preço': 'tcgcsv', 'Validation Status': 'VALIDATED_REAL',
           'Condição': 'NM', 'Idioma': 'EN', 'Scanned At': '2026-09-06',
           'Link TCG': 'https://example.org/reference', 'Link CardTrader': 'https://example.org/offer'}
    return dict(row, **changes)


def test_actual_ct_export_normalization_and_matching(tmp_path):
    path = tmp_path / 'source.xlsx'
    pd.DataFrame([ct_row()]).to_excel(path, index=False)
    ct = read_ct(path, 9)[0]
    assert canonical_set_of(ct) == 'PRE'
    assert ct.fx == 5
    assert ct.price_source == 'tcgcsv' and ct.scanned_at == '2026-09-06'
    assert ct.review_reasons == ['variante de baixa confiança na fonte']
    myp = Deal(fonte='MYP', carta='Eevee', numero='74', set_name='Prismatic Evolutions',
               variant='reverseHolofoil', condition='NM', language='EN', price_status='real', compra_brl=120)
    match = group_cross_source([ct, myp])
    assert len(match) == 1 and match[0].validar
    assert 'baixa confiança' in match[0].motivo
    myp.variant = 'holofoil'
    assert group_cross_source([ct, myp]) == []
    myp.variant = ''
    uncertain = group_cross_source([ct, myp])
    assert len(uncertain) == 1 and uncertain[0].validar
    assert 'variante não informada' in uncertain[0].motivo
    second_finish = ct_row_to_deal(ct_row(Variant='holofoil'), 5)
    assert group_cross_source([ct, second_finish, myp]) == []
    ct.set_name = 'Surging Sparks (pre)'
    assert canonical_set_of(ct) is None


def test_unvalidated_near_miss_is_never_clean():
    d = ct_row_to_deal(ct_row(**{'Scan R$ (raw)': 150, 'Validation Status': 'NOT_VALIDATED'}), 5)
    assert d.margem_pct > 30  # CT discount is <30, unified ROI is >30
    assert bucket_for(d) == 'Validar manualmente'


def test_delivery_retains_all_buckets_and_missing_price():
    clean = ct_row_to_deal(ct_row(**{'Variante Baixa Confiança': ''}), 5)
    missing = Deal(fonte='MYP', carta='No price', compra_brl=50)
    fallback = Deal(fonte='MYP', carta='Estimated', compra_brl=50, ref_brl=100,
                    margem_pct=100, price_status='fallback')
    low = ct_row_to_deal(ct_row(**{'Scan R$ (raw)': 210}), 5)
    md = build_markdown([clean, missing, fallback, low], [], 5)
    assert 'Eevee 074' in md and '| Carta | Set |' in md
    assert '[40.00](https://example.org/reference)' in md
    assert 'Fallback — margem estimada' in md and 'Abaixo do corte' in md
    no_price_row = next(x for x in md.splitlines() if '| No price |' in x)
    assert [c.strip() for c in no_price_row.split('|')][5:8] == ['—', '—', '—']
    assert md.count('[oferta]') == 2


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(run, 'OUT_DIR', tmp_path/'out')
    monkeypatch.setattr(run, 'LOG_DIR', tmp_path/'logs')
    monkeypatch.setattr(run, 'fresh_fx', lambda: 5)
    stores = []
    monkeypatch.setattr(run, 'save_store', lambda data, **kw: stores.append((data, kw)))
    return tmp_path, stores


def test_live_failure_never_discovers_old_output(monkeypatch, isolated):
    root, stores = isolated
    stale = root/'old.xlsx'
    pd.DataFrame([ct_row()]).to_excel(stale, index=False)
    monkeypatch.setattr(run, 'latest_ct_output', lambda: pytest.fail('stale finder invoked'))
    monkeypatch.setattr(run, 'scan_ct', lambda *a: ('falhou', 'exit code 1; original cause', 1, None))
    monkeypatch.setattr(sys, 'argv', ['run', '--sets', 'PRE', '--sources', 'ct'])
    assert run.main() == 1
    store = stores[0][0]
    assert store['deals'] == [] and store['run_status'] == 'failed'
    assert 'original cause' in store['sources'][0]['detail']


def test_partial_preserves_current_rows(monkeypatch, isolated):
    root, stores = isolated
    path = root/'partial.xlsx'
    pd.DataFrame([ct_row()]).to_excel(path, index=False)
    monkeypatch.setattr(run, 'scan_ct', lambda *a: ('parcial', 'blocked', 1, path))
    monkeypatch.setattr(sys, 'argv', ['run', '--sources', 'ct', '--sets', 'PRE'])
    assert run.main() == 2
    assert stores[0][0]['deal_count'] == 1
    assert stores[0][0]['run_status'] == 'partial'


def test_explicit_historical_read_does_not_overwrite_live_store(monkeypatch, isolated):
    root, stores = isolated
    path = root/'old.xlsx'
    pd.DataFrame([ct_row()]).to_excel(path, index=False)
    monkeypatch.setattr(sys, 'argv', ['run', '--skip-scan', '--sources', 'ct', '--ct-output', str(path)])
    assert run.main() == 0
    data, kwargs = stores[0]
    assert data['mode'] == 'historical' and data['scope'] == 'historical: unknown'
    assert 'historical_store_' in kwargs['path'].name
    assert data['sources'][0]['collected_at']


def test_source_commands_use_fresh_state_and_selected_provider(monkeypatch, tmp_path):
    monkeypatch.setattr(run, 'REPOS', {'ct': tmp_path, 'myp': tmp_path})
    calls = []
    monkeypatch.setattr(run, '_run_step', lambda name, cmd, *a, **kw: (calls.append(cmd) or ('falhou', '', 0)))
    run.scan_ct(resolve_scope('PRE'), 'RUN_A', 60)
    first = calls[-1]
    run.scan_ct(resolve_scope('PRE'), 'RUN_B', 60, 'pokemontcg')
    second = calls[-1]
    assert first[first.index('--provider')+1] == 'tcgcsv'
    assert first[first.index('--state-dir')+1] != second[second.index('--state-dir')+1]
    assert '--no-cache' in first
    run.scan_myp(resolve_scope('PRE'), 'RUN_C', 60, 'tcgcsv', 2)
    assert '--resume' not in calls[-1] and '--max-products' in calls[-1]


def test_group2_verified_codes_cover_all_requested_editions():
    scope = resolve_scope('group2')
    assert len(scope) == 14
    assert to_ct_sets(scope)[0] == ['paf','par','obf','mew','pal','blk','wht','crz','sit','lorg','astr','brs','fst','evs']
    assert len(to_myp_editions(scope)[0]) == 14


def test_api_job_exposes_partial(monkeypatch, tmp_path):
    monkeypatch.setattr(api_store, 'OUT_DIR', tmp_path)
    monkeypatch.setattr(api.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=2))
    monkeypatch.setattr(api, '_JOBS', {'test': {}})
    api._run_scan_job('test', api.ScanRequest(sets='PRE'))
    assert api._JOBS['test']['status'] == 'partial'


def test_myp_preserves_real_usd_and_source_fx():
    d = myp_row_to_deal({'Card Name': 'Test (1/100)', 'TCG Player (R$)': 500,
                        'TCG US$': 100, 'TCG Source': 'real (tcgcsv)', 'MYP EN NM (R$)': 250}, 9)
    assert d.ref_usd == 100 and d.fx == 5 and d.compra_usd == 50


def test_myp_reads_all_cards_including_below_cutoff_once(tmp_path):
    from normalize import read_myp
    path = tmp_path/'myp.xlsx'
    rows = [{'Card Name': 'Above', 'MYP EN NM (R$)': 50, 'TCG Player (R$)': 100},
            {'Card Name': 'Below', 'MYP EN NM (R$)': 90, 'TCG Player (R$)': 100}]
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame(rows[:1]).to_excel(writer, sheet_name='🔥 Deals', index=False)
        pd.DataFrame(rows).to_excel(writer, sheet_name='All EN Cards', index=False)
    assert [d.carta for d in read_myp(path, 5)] == ['Above', 'Below']
