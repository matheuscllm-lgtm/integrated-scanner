"""Formato da tabela de ENTREGA (markdown no chat) — `delivery.build_markdown`.

Trava o padrão cross-scanner do operador (2026-06-19): coluna `Links` ÚNICA
combinando oferta + TCG (`[oferta](url) · [TCG](url)`), modelo de tabela do MYP.
O XLSX de apoio mantém as 2 colunas de URL cruas separadas — só a entrega combina.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from delivery import build_markdown
from normalize import Deal


def _deal(**kw):
    base = dict(
        fonte="CT", carta="Glaceon ex", numero="150", margem_pct=35.0,
        link_oferta="https://www.cardtrader.com/cards/1",
        link_tcg="https://prices.pokemontcg.io/tcgplayer/sv8pt5-150",
    )
    base.update(kw)
    return Deal(**base)


def test_delivery_has_single_combined_links_column():
    md = build_markdown([_deal()], statuses=[], fx_global=5.0, min_margin_pct=30.0)
    assert "| Links |" in md           # coluna única combinada
    assert "Link oferta" not in md      # 2 colunas cruas saem da ENTREGA
    assert "Link TCG" not in md


def test_delivery_links_cell_combined_format():
    md = build_markdown([_deal()], statuses=[], fx_global=5.0, min_margin_pct=30.0)
    assert "[oferta](https://www.cardtrader.com/cards/1)" in md
    assert "[TCG](https://prices.pokemontcg.io/tcgplayer/sv8pt5-150)" in md
    assert " · " in md                  # separador oferta · TCG


def test_delivery_links_dash_when_missing():
    md = build_markdown([_deal(link_oferta="", link_tcg="")], statuses=[],
                        fx_global=5.0, min_margin_pct=30.0)
    assert "[oferta]" not in md
    assert "[TCG](" not in md            # célula vira "—" sem quebrar a tabela
