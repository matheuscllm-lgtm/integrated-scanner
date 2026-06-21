"""Testes da normalização por fonte: convenções de margem, FX, schema."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from normalize import (UNIFIED_COLUMNS, classify_chase_tier, clean_myp_edition,
                       comc_row_to_deal, comc_run_summaries,
                       compute_valorization, ct_row_to_deal, gross_margin_pct,
                       liga_row_to_deal, myp_row_to_deal)

FX = 5.20


# ── linha real (anonimizada) de cada fonte ───────────────────────────────────
CT_ROW = {
    "Card Name": "Milcery", "Set": "Stellar Crown (scr)", "Nº": 152,
    "Rarity": "Illustration Rare", "Condição": "Near Mint", "Idioma": "EN",
    "Scan R$ (raw)": 53.75, "LIVE R$ (real)": 61.92,
    "TCG Market (BRL)": 96.24, "TCG Market (USD)": 18.64,
    "Margem % REAL": 0.3566,  # FRAÇÃO, base = revenda (convenção CT)
    "Qtd": 1, "Chase Tier": "TOP", "Valorização (0-100)": 90,
    "Valorização — Notas": "raridade top (...)",
    "Validation Status": "VALIDATED_MARKUP",
    "Link CardTrader": "https://www.cardtrader.com/cards/299015",
    "Link TCG": "https://prices.pokemontcg.io/tcgplayer/sv7-152",
}
MYP_ROW = {
    "Card Name": "Mega Gengar ex (269/217)", "Edition": "ME: Ascended Heroes",
    "Rarity": "Rara", "MYP EN NM (R$)": 250, "TCG Player (R$)": 446.0,
    "Margin %": 0.784,  # FRAÇÃO, base = compra (convenção MYP)
    "NM Sellers": 19, "⚠️ COLLECTOR#": "⚠️ VARIANT",
    "URL": "https://mypcards.com/pokemon/produto/310506/mega-gengar-ex",
}
COMC_ROW = {
    "card": "Paldean Wooper - 221/193", "number": "221/193",
    "set": "SV02: Paldea Evolved", "rarity": "Illustration Rare",
    "condition": "NM", "comc_price": 12.32, "tcg_reference": 14.27,
    "margin_pct": 13.67,  # PERCENT, base = revenda (convenção COMC)
    "quantity": 7, "confidence": 0.95,
    "comc_url": "https://www.comc.com/x", "tcg_url": "https://www.tcgplayer.com/x",
}
LIGA_ROW = {
    "card_name": "Charizard ex", "set_name": "Obsidian Flames",
    "price_liga_brl": 180.0, "price_tcg_usd": 55.0, "price_tcg_brl": 286.0,
    "margin_percent": 58.89,  # PERCENT, base = compra (convenção Liga)
    "exchange_rate": 5.2,
    "liga_url": "https://liga/x", "tcg_url": "https://tcg/x",
}


def test_gross_margin_base_is_purchase():
    # (revenda − compra)/compra: 100→150 = +50%
    assert gross_margin_pct(150.0, 100.0) == pytest.approx(50.0)
    assert gross_margin_pct(100.0, 0.0) == 0.0  # sem divisão por zero


def test_ct_margin_recomputed_over_purchase():
    d = ct_row_to_deal(CT_ROW, FX)
    # CT reportava 35.66% (base revenda); unificado = (96.24−61.92)/61.92
    assert d.margem_pct == pytest.approx(55.43, abs=0.05)
    assert d.compra_brl == 61.92          # usa LIVE (validado), não o raw
    assert d.fx == pytest.approx(96.24 / 18.64, abs=0.001)  # FX implícito da linha
    assert d.qtd == 1
    assert d.valorizacao == 90            # score vem pronto do CT
    assert d.chase_tier == "TOP"


def test_ct_falls_back_to_scan_price_without_live():
    row = dict(CT_ROW, **{"LIVE R$ (real)": 0})
    d = ct_row_to_deal(row, FX)
    assert d.compra_brl == 53.75


def test_myp_number_extracted_and_margin_recomputed():
    d = myp_row_to_deal(MYP_ROW, FX)
    assert d.carta == "Mega Gengar ex"
    assert d.numero == "269"
    # (446−250)/250 = 78.4% — bate com a própria convenção do MYP
    assert d.margem_pct == pytest.approx(78.4, abs=0.05)
    assert d.qtd is None                  # MYP não informa estoque
    assert d.valorizacao is not None      # heurística portada preenche
    assert d.notorio.startswith("⭐")      # Gengar é notório
    assert any("COLLECTOR#" in n for n in d.notas)  # alertas preservados


def test_comc_usd_converted_with_global_fx():
    d = comc_row_to_deal(COMC_ROW, FX)
    assert d.compra_usd == 12.32
    assert d.compra_brl == pytest.approx(12.32 * FX)
    # (14.27−12.32)/12.32 = 15.83% (a fonte dizia 13.67% base revenda)
    assert d.margem_pct == pytest.approx(15.83, abs=0.05)
    assert d.qtd == 7
    assert d.chase_tier == "TOP"          # Illustration Rare


def test_liga_uses_row_exchange_rate():
    d = liga_row_to_deal(LIGA_ROW, 99.0)  # fx global absurdo de propósito
    assert d.fx == 5.2                    # linha ganha do global
    assert d.margem_pct == pytest.approx(58.89, abs=0.05)
    assert d.notorio == "⭐ Charizard"


def test_unified_row_has_all_columns():
    for deal in (ct_row_to_deal(CT_ROW, FX), myp_row_to_deal(MYP_ROW, FX),
                 comc_row_to_deal(COMC_ROW, FX), liga_row_to_deal(LIGA_ROW, FX)):
        row = deal.to_row()
        assert list(row.keys()) == UNIFIED_COLUMNS


def test_chase_tier_port_matches_ct_behavior():
    assert classify_chase_tier("Special Illustration Rare") == "TOP"
    assert classify_chase_tier("Double Rare") == "MID"
    assert classify_chase_tier("Comum") == "BULK"
    assert classify_chase_tier("Rara") == "MODEST"   # não mapeada → conservador
    assert classify_chase_tier(None) == ""


def test_valorization_heuristic_components():
    score, note = compute_valorization("Special Illustration Rare", None, 120.0)
    # 45 (TOP) + 10 (sem data) + 20 (>$100) = 75
    assert score == 75
    assert "sem série histórica" in note


def test_clean_myp_edition_splits_pt_en():
    # casos-alvo reais (catálogo MYP concatena PT+EN sem separador)
    assert clean_myp_edition(
        "Escarlate e Violeta: Máscaras do CrepúsculoSV06: Twilight Masquerade"
    ) == "SV06: Twilight Masquerade"
    assert clean_myp_edition(
        "Escarlate e Violeta: 151Scarlet & Violet—151"
    ) == "Scarlet & Violet—151"
    # título EN-only fica intacto (não há boundary PT→EN)
    assert clean_myp_edition("ME: Ascended Heroes") == "ME: Ascended Heroes"
    assert clean_myp_edition("Surging Sparks") == "Surging Sparks"
    # vintage/promo não mapeado fica intacto (cosmético residual aceitável)
    assert clean_myp_edition("Coleção Clássica") == "Coleção Clássica"
    assert clean_myp_edition("") == ""


def test_myp_set_name_uses_clean_edition():
    row = dict(MYP_ROW, Edition=(
        "Escarlate e Violeta: Máscaras do CrepúsculoSV06: Twilight Masquerade"))
    d = myp_row_to_deal(row, FX)
    assert d.set_name == "SV06: Twilight Masquerade"


def test_myp_link_tcg_from_column():
    url = "https://prices.pokemontcg.io/tcgplayer/sv7-152"
    row = dict(MYP_ROW, **{"TCG URL": url})
    d = myp_row_to_deal(row, FX)
    assert d.link_tcg == url


def test_myp_link_tcg_fallback_search():
    # XLSX antigo (pré-v5.11.2) sem a coluna → busca por nome SEM o (NNN/MMM)
    d = myp_row_to_deal(MYP_ROW, FX)
    assert "tcgplayer.com/search" in d.link_tcg
    assert "Mega+Gengar+ex" in d.link_tcg
    assert "269" not in d.link_tcg
    # coluna presente mas vazia (NaN do pandas) → também cai no fallback
    d2 = myp_row_to_deal(dict(MYP_ROW, **{"TCG URL": float("nan")}), FX)
    assert "tcgplayer.com/search" in d2.link_tcg


def _has_fallback_note(deal):
    return any("MARGEM NÃO-CONFIÁVEL" in n and "FALLBACK" in n for n in deal.notas)


def test_myp_real_price_no_fallback_note():
    # Preço REAL (TCG Source = pokemontcg.io) → SEM nota de margem não-confiável.
    row = dict(MYP_ROW, **{"TCG Source": "real (pokemontcg.io)", "TCG US$": 86.0})
    d = myp_row_to_deal(row, FX)
    assert not _has_fallback_note(d), f"deal real não devia ter nota de fallback: {d.notas}"


def test_myp_fallback_price_gets_untrustworthy_note_first():
    # Preço FALLBACK (.estat-tcg) → nota de MARGEM NÃO-CONFIÁVEL, e em PRIMEIRO
    # lugar (é a ressalva mais importante: a margem pode ser ilusória — Darumaka).
    row = dict(MYP_ROW, **{"TCG Source": "fallback (.estat-tcg)", "TCG US$": float("nan"),
                           "TCG Player (R$)": 2867.0, "MYP EN NM (R$)": 60.0})
    d = myp_row_to_deal(row, FX)
    assert _has_fallback_note(d), f"deal fallback devia ter nota de margem não-confiável: {d.notas}"
    assert "MARGEM NÃO-CONFIÁVEL" in d.notas[0], \
        f"a nota de fallback devia ser a PRIMEIRA: {d.notas}"


def test_myp_fallback_inference_old_xlsx():
    # XLSX antigo SEM 'TCG Source': infere por 'TCG US$'. Com USD → real (sem nota);
    # sem USD → tratado como fallback (flag conservador/honesto).
    real_old = dict(MYP_ROW, **{"TCG US$": 30.0})   # tem USD, sem TCG Source
    assert not _has_fallback_note(myp_row_to_deal(real_old, FX))
    fb_old = dict(MYP_ROW)  # nem TCG Source nem TCG US$ → desconhecido → flag
    assert _has_fallback_note(myp_row_to_deal(fb_old, FX))


def test_read_liga_keeps_only_approved(tmp_path):
    # e2e 2026-06-10: piso R$50 da Liga marca carta de centavos como
    # "rejected"; o integrado deve respeitar o veredito da fonte.
    import json
    from normalize import read_liga
    rows = [
        dict(LIGA_ROW, status="approved"),
        dict(LIGA_ROW, card_name="Applin", price_liga_brl=0.08,
             price_tcg_brl=0.47, status="rejected"),
        dict(LIGA_ROW, card_name="Sem Status"),  # sem campo → fora (conservador)
    ]
    p = tmp_path / "report_x.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    deals = read_liga(p, 5.2)
    assert [d.carta for d in deals] == ["Charizard ex"]


def test_comc_run_summaries(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    (results / "comc_deals_recent_latest.json").write_text(
        '{"era": "recent", "generated_utc": "20260610T184632Z", "count": 0, "deals": []}',
        encoding="utf-8")
    (results / "comc_deals_vintage_latest.json").write_text(
        "{json quebrado", encoding="utf-8")  # ilegível → era ignorada
    s = comc_run_summaries(tmp_path)
    assert set(s.keys()) == {"recent"}
    assert s["recent"]["count"] == 0
    assert s["recent"]["generated_utc"] == "20260610T184632Z"
    # diretório sem nenhum sidecar → dict vazio
    assert comc_run_summaries(tmp_path / "nao_existe") == {}
