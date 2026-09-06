"""Offline coverage for slower MYP requests and complete group time budgets."""
import sys
from types import SimpleNamespace

import pytest

import api
import api_store
import run_integrated as run
from set_registry import resolve_scope


@pytest.mark.parametrize('extra,delay,timeout', [
    ([], 3.0, 7 * 3600),
    (['--myp-delay', '4.25', '--timeout', '600'], 4.25, 600),
])
def test_group2_cli_propagates_pacing_and_full_budget(monkeypatch, tmp_path, extra, delay, timeout):
    calls, stores = [], []
    def fake_myp(scope, stamp, timeout_s, provider, max_products, delay_s):
        calls.append((len(scope), timeout_s, max_products, delay_s))
        return 'ok', '', 0, tmp_path / 'current.xlsx'
    monkeypatch.setattr(run, 'scan_myp', fake_myp)
    monkeypatch.setattr(run, 'read_myp', lambda *a: [])
    monkeypatch.setattr(run, 'fresh_fx', lambda: 5)
    monkeypatch.setattr(run, 'OUT_DIR', tmp_path)
    monkeypatch.setattr(run, 'write_xlsx', lambda *a: None)
    monkeypatch.setattr(run, 'save_store', lambda value, **kw: stores.append(value))
    monkeypatch.setattr(sys, 'argv', ['run', '--profile', 'group2', '--sources', 'myp', *extra])
    assert run.main() == 0
    assert calls == [(14, timeout, 0, delay)]
    assert stores[0]['myp_delay_s'] == delay
    assert stores[0]['diagnostic_limit'] == 0


def test_source_timeouts_preserve_overrides_and_other_sources():
    group = resolve_scope('group2')
    assert run.source_timeout('myp', group) == 7 * 3600
    assert run.source_timeout('ct', group) == run.TIMEOUTS['ct']['quick']
    assert run.source_timeout('myp', resolve_scope('full')) == run.TIMEOUTS['myp']['full']
    assert run.source_timeout('myp', group, 123) == 123


@pytest.mark.parametrize('value', ['0', '-1', 'nan', 'inf'])
def test_cli_rejects_invalid_delay_before_collection(monkeypatch, value):
    monkeypatch.setattr(run, 'fresh_fx', lambda: pytest.fail('no collection may start'))
    monkeypatch.setattr(sys, 'argv', ['run', '--myp-delay', value])
    with pytest.raises(SystemExit) as exc:
        run.main()
    assert exc.value.code == 2


@pytest.mark.parametrize('value', [0, -1, float('nan'), float('inf')])
def test_api_rejects_invalid_delay(value):
    with pytest.raises(ValueError):
        api.ScanRequest(sets='group2', myp_delay_s=value)


def test_api_forwards_custom_delay_without_changing_scope(monkeypatch, tmp_path):
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(api.subprocess, 'run', fake_run)
    monkeypatch.setattr(api_store, 'OUT_DIR', tmp_path)
    monkeypatch.setattr(api, '_JOBS', {'pacing': {}})
    api._run_scan_job('pacing', api.ScanRequest(sets='group2', myp_delay_s=4.0))
    cmd = calls[0]
    assert cmd[cmd.index('--sets')+1] == 'group2'
    assert cmd[cmd.index('--myp-delay')+1] == '4.0'
    assert '--myp-max-products' in cmd and cmd[cmd.index('--myp-max-products')+1] == '0'
    assert api._JOBS['pacing']['status'] == 'done'
