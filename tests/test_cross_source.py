"""Cross-source card matching — casar a MESMA carta entre as 4 fontes.

Trava o contrato do `cross_source.py` + a seção de entrega lado-a-lado:
  - normalização de número de coleção e de nome (entre convenções das fontes);
  - reversão set→canônico por convenção de CADA fonte (MYP substring de título,
    Liga nome completo, CT code, COMC nome/slug; set desconhecido → None);
  - agrupamento CONSERVADOR: âncora = set canônico + número; Liga (sem número)
    casada por nome vira `validar`; colisão de número entre Pokémon diferentes
    vira `validar`; carta de 1 fonte só (ou set não-resolvido) NÃO entra;
  - a tabela de entrega põe o preço de cada fonte lado a lado, marca a mais
    barata (⬅) e a flag `validar`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cross_source import (canonical_set_of, group_cross_source,
                          normalize_card_name, normalize_card_number)
from delivery import build_cross_source_markdown
from normalize import Deal


def _deal(fonte, carta, set_name, numero="", compra_brl=100.0, ref_brl=150.0,
          margem_pct=50.0, link_oferta="", link_tcg=""):
    return Deal(fonte=fonte, carta=carta, set_name=set_name, numero=numero,
                compra_brl=compra_brl, ref_brl=ref_brl, margem_pct=margem_pct,
                link_oferta=link_oferta, link_tcg=link_tcg)


# ── normalização de número ──────────────────────────────────────────────────
def test_normalize_number_strips_set_total_and_leading_zeros():
    assert normalize_card_number("173/165") == "173"
    assert normalize_card_number("013/110") == "13"
    assert normalize_card_number("161") == "161"
    assert normalize_card_number("") == ""


def test_normalize_number_keeps_letter_prefix():
    assert normalize_card_number("TG12/TG30") == "tg12"
    assert normalize_card_number("SV045/SV122") == "sv45"


# ── normalização de nome ────────────────────────────────────────────────────
def test_normalize_name_drops_collector_number_and_case():
    assert normalize_card_name("Umbreon ex (161/131)") == "umbreon ex"
    assert normalize_card_name("Umbreon EX") == "umbreon ex"
    assert normalize_card_name("Pikachu 173/165") == "pikachu"
    assert normalize_card_name("Charizard ex - 223/197") == "charizard ex"


# ── reversão set → canônico por fonte ───────────────────────────────────────
def test_canonical_set_myp_substring_title():
    # MYP emite o título EN inteiro; casa pela substring tunada do registry
    d = _deal("MYP", "Pikachu ex", "SV08: Surging Sparks", "238")
    assert canonical_set_of(d) == "SSP"


def test_canonical_set_liga_full_name():
    d = _deal("Liga", "Umbreon ex", "Prismatic Evolutions")
    assert canonical_set_of(d) == "PRE"


def test_canonical_set_ct_code_and_name():
    assert canonical_set_of(_deal("CardTrader", "x", "pre")) == "PRE"
    assert canonical_set_of(_deal("CardTrader", "x", "Prismatic Evolutions")) == "PRE"


def test_canonical_set_comc_name_and_slug():
    assert canonical_set_of(_deal("COMC", "x", "Stellar Crown")) == "SCR"
    assert canonical_set_of(_deal("COMC", "x", "stellar-crown")) == "SCR"


def test_canonical_set_unknown_is_none():
    assert canonical_set_of(_deal("MYP", "x", "Coleção Inexistente 99")) is None
    assert canonical_set_of(_deal("Liga", "x", "")) is None


# ── agrupamento ─────────────────────────────────────────────────────────────
def test_same_card_by_number_across_sources_no_flag():
    deals = [
        _deal("MYP", "Umbreon ex (161/131)", "Prismatic Evolutions", "161",
              compra_brl=900.0, ref_brl=1200.0, margem_pct=33.3),
        _deal("CardTrader", "Umbreon ex", "pre", "161",
              compra_brl=850.0, ref_brl=1200.0, margem_pct=41.2),
    ]
    cards = group_cross_source(deals)
    assert len(cards) == 1
    c = cards[0]
    assert c.canonical_set == "PRE"
    assert c.number == "161"
    assert set(c.sources) == {"MYP", "CardTrader"}
    assert c.cheapest_source == "CardTrader"   # 850 < 900
    assert c.validar is False                  # número casa + mesmo Pokémon


def test_liga_without_number_matched_by_name_is_validar():
    deals = [
        _deal("MYP", "Umbreon ex (161/131)", "Prismatic Evolutions", "161",
              compra_brl=900.0),
        _deal("Liga", "Umbreon ex", "Prismatic Evolutions", numero="",
              compra_brl=880.0),
    ]
    cards = group_cross_source(deals)
    assert len(cards) == 1
    assert set(cards[0].sources) == {"MYP", "Liga"}
    assert cards[0].validar is True
    assert "nome" in cards[0].motivo.lower()


def test_number_collision_different_pokemon_not_grouped():
    # mesmo set + mesmo número mas Pokémon diferente (mapeamento furado de uma
    # fonte) → NÃO vira uma linha enganosa: cada um some do cross-source
    deals = [
        _deal("MYP", "Umbreon ex", "Prismatic Evolutions", "161"),
        _deal("COMC", "Espeon ex", "Prismatic Evolutions", "161"),
    ]
    assert group_cross_source(deals) == []


def test_number_collision_real_match_survives_bad_mapping_drops():
    # 2 fontes concordam (Umbreon #161); 1 fonte mapeou #161 como Espeon (erro).
    # O match real sobrevive; o mapeamento furado é excluído (não polui a linha).
    deals = [
        _deal("MYP", "Umbreon ex", "Prismatic Evolutions", "161", compra_brl=900),
        _deal("CardTrader", "Umbreon ex", "pre", "161", compra_brl=820),
        _deal("COMC", "Espeon ex", "Prismatic Evolutions", "161", compra_brl=300),
    ]
    cards = group_cross_source(deals)
    assert len(cards) == 1
    c = cards[0]
    assert c.display_name == "Umbreon ex"
    assert set(c.sources) == {"MYP", "CardTrader"}     # COMC/Espeon NÃO entra
    assert c.cheapest_source == "CardTrader"           # 820, não os 300 do Espeon
    assert c.validar is False


def test_variant_suffix_collision_split():
    # mesmo Pokémon, MESMO número, variante diferente (ex vs V) = cartas
    # diferentes → não agrupa ({umbreon,ex} vs {umbreon,v} não é subconjunto)
    deals = [
        _deal("MYP", "Umbreon ex", "Prismatic Evolutions", "161"),
        _deal("CardTrader", "Umbreon V", "pre", "161"),
    ]
    assert group_cross_source(deals) == []


def test_bare_name_does_not_bridge_variants_clique():
    # REGRESSÃO (bug do union-find, P1): o predicado de nome (subconjunto de
    # tokens) NÃO é transitivo. "umbreon" ⊆ "umbreon ex" E "umbreon" ⊆ "umbreon
    # v", mas "umbreon ex" e "umbreon v" são cartas DIFERENTES. Num union-find o
    # pelado fazia a PONTE e as 3 viravam 1 card ("nome de uma + preço de outra").
    # Com clustering por CLIQUE, ex e v NUNCA caem no mesmo card mesmo com o pelado.
    deals = [
        _deal("MYP", "Umbreon ex", "Prismatic Evolutions", "161", compra_brl=900),
        _deal("CardTrader", "Umbreon V", "pre", "161", compra_brl=300),
        _deal("COMC", "Umbreon", "Prismatic Evolutions", "161", compra_brl=500),
    ]
    cards = group_cross_source(deals)
    # nenhum card pode conter ex E v na mesma linha
    for c in cards:
        names = {normalize_card_name(d.carta) for d in c.deals_by_source.values()}
        assert not ({"umbreon ex"} <= names and "umbreon v" in names), (
            "ex e V não podem ser fundidos no mesmo card")
    # as três fontes nomeiam coisas distintas/ambíguas → nenhuma fusão silenciosa
    # de duas variantes diferentes; cada variante específica fica isolada (1 fonte
    # só → some do cross-source). O resultado NÃO entrega ex+V como uma carta.
    assert all(c.cheapest_source != "CardTrader" or
               normalize_card_name(c.cheapest_deal.carta) != "umbreon v"
               for c in cards if normalize_card_name(c.display_name) == "umbreon ex")


def test_multiword_name_collision_split():
    # 'Mr. Mime' vs 'Mr. Rime' no mesmo número → {mr,mime} vs {mr,rime}
    # não-compatíveis → não agrupa (antes, comparar só o 1º token os fundia)
    deals = [
        _deal("MYP", "Mr. Mime", "151", "122"),
        _deal("COMC", "Mr. Rime", "151", "122"),
    ]
    assert group_cross_source(deals) == []


def test_subset_name_stays_grouped_no_flag():
    # 'Umbreon' (fonte omitiu o sufixo) ⊆ 'Umbreon ex' = mesma carta → agrupa,
    # sem flag (nome compatível, número casa)
    deals = [
        _deal("MYP", "Umbreon", "Prismatic Evolutions", "161", compra_brl=900),
        _deal("CardTrader", "Umbreon ex", "pre", "161", compra_brl=820),
    ]
    cards = group_cross_source(deals)
    assert len(cards) == 1
    assert cards[0].display_name == "Umbreon ex"   # exibe o nome mais completo
    assert cards[0].validar is False


def test_single_source_card_not_returned():
    deals = [_deal("MYP", "Umbreon ex", "Prismatic Evolutions", "161")]
    assert group_cross_source(deals) == []


def test_two_deals_same_source_not_cross_source():
    deals = [
        _deal("MYP", "Umbreon ex", "Prismatic Evolutions", "161", compra_brl=900.0),
        _deal("MYP", "Umbreon ex", "Prismatic Evolutions", "161", compra_brl=950.0),
    ]
    assert group_cross_source(deals) == []   # 1 fonte só não é cross-source


def test_unresolved_set_excluded_from_grouping():
    deals = [
        _deal("MYP", "Umbreon ex", "Coleção Fantasma", "161"),
        _deal("CardTrader", "Umbreon ex", "Coleção Fantasma", "161"),
    ]
    assert group_cross_source(deals) == []   # set não-resolvido → fora


def test_different_numbers_same_name_not_merged():
    # mesmo Pokémon, números diferentes no mesmo set = cartas diferentes
    deals = [
        _deal("MYP", "Pikachu", "Surging Sparks", "238"),
        _deal("CardTrader", "Pikachu", "Surging Sparks", "94"),
    ]
    assert group_cross_source(deals) == []


def test_sorted_by_cheapest_buy_margin_desc():
    deals = [
        # carta A: mais barata = COMC com margem ~50%
        _deal("MYP", "Sylveon ex", "Surging Sparks", "86", compra_brl=200, ref_brl=260, margem_pct=30),
        _deal("COMC", "Sylveon ex", "Surging Sparks", "86", compra_brl=180, ref_brl=270, margem_pct=50),
        # carta B: mais barata = CardTrader com margem ~100%
        _deal("MYP", "Latias ex", "Surging Sparks", "76", compra_brl=100, ref_brl=180, margem_pct=80),
        _deal("CardTrader", "Latias ex", "Surging Sparks", "76", compra_brl=90, ref_brl=180, margem_pct=100),
    ]
    cards = group_cross_source(deals)
    assert [c.display_name for c in cards][0].startswith("Latias")  # 100% antes de 50%


# ── tabela de entrega ───────────────────────────────────────────────────────
def test_markdown_empty_when_no_cross_source():
    assert "Nenhuma carta passou o corte em 2+ fontes" in build_cross_source_markdown([])


def test_markdown_lays_prices_side_by_side_and_marks_cheapest():
    deals = [
        _deal("MYP", "Umbreon ex (161/131)", "Prismatic Evolutions", "161",
              compra_brl=900.0, ref_brl=1200.0, margem_pct=33.3,
              link_oferta="https://mypcards.com/u", link_tcg="https://tcg/u"),
        # CardTrader é a MAIS BARATA (850) → a célula Links usa os links dela
        _deal("CardTrader", "Umbreon ex", "pre", "161",
              compra_brl=850.0, ref_brl=1200.0, margem_pct=41.2,
              link_oferta="https://cardtrader.com/u", link_tcg="https://tcg/ct-u"),
    ]
    md = build_cross_source_markdown(group_cross_source(deals))
    assert "MYP R$" in md and "CardTrader R$" in md and "Liga R$" in md
    assert "900.00" in md and "850.00" in md      # os dois preços lado a lado
    assert "⬅" in md                              # marca a mais barata
    assert "CardTrader (R$850.00)" in md          # coluna "Mais barata"
    assert "[oferta](https://cardtrader.com/u)" in md  # links da fonte mais barata


def test_markdown_flags_validar_rows():
    deals = [
        _deal("MYP", "Umbreon ex (161/131)", "Prismatic Evolutions", "161", compra_brl=900.0),
        _deal("Liga", "Umbreon ex", "Prismatic Evolutions", numero="", compra_brl=880.0),
    ]
    md = build_cross_source_markdown(group_cross_source(deals))
    assert "validar" in md
