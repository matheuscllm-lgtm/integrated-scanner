"""Testes dos helpers de status do orquestrador (COMC 0-deals + staleness Liga)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from run_integrated import (LIGA_CSV_MAX_AGE_H, _comc_phase2_status,
                            _staleness_warning)


def test_comc_phase2_status_zero_deals():
    # sidecar com count==0 prova scan bem-sucedido → "ok (0 deals)", não
    # "indisponível" (bug do run 2026-06-10: COMC rodou 7,7 min e saiu
    # rotulado "nenhum output encontrado")
    st, det = _comc_phase2_status(
        [], {"recent": {"count": 0, "generated_utc": "20260610T184632Z"}})
    assert st == "ok (0 deals)"
    assert "recent: 0 deals" in det
    assert "20260610T184632Z" in det


def test_comc_phase2_status_no_output():
    st, det = _comc_phase2_status([], {})
    assert st == "indisponível"
    assert det == "nenhum output encontrado"


def test_comc_phase2_status_both_eras_zero():
    st, det = _comc_phase2_status([], {
        "recent": {"count": 0, "generated_utc": "A"},
        "vintage": {"count": 0, "generated_utc": "B"},
    })
    assert st == "ok (0 deals)"
    assert "recent: 0 deals" in det and "vintage: 0 deals" in det


def test_comc_phase2_status_sidecar_with_deals_but_csv_sumido():
    # sidecar diz count>0 mas o CSV não foi achado → algo errado de verdade;
    # NÃO pode virar "ok (0 deals)"
    st, det = _comc_phase2_status([], {"recent": {"count": 5, "generated_utc": "X"}})
    assert st == "indisponível"


def test_staleness_warning_boundary():
    now = 1_000_000_000.0
    h = 3600.0
    # 47h → fresco
    assert _staleness_warning(now - 47 * h, now=now) is None
    # exatamente no limite → ainda fresco (<=)
    assert _staleness_warning(now - LIGA_CSV_MAX_AGE_H * h, now=now) is None
    # 49h → aviso com a idade e a sugestão de re-coleta
    w = _staleness_warning(now - 49 * h, now=now)
    assert w is not None
    assert "49h" in w
    assert "re-coletar" in w
