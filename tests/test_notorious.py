"""Testes do matcher de Pokémon notórios (palavra inteira, sem falso positivo)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from notorious import is_notorious, match_notorious


def test_charizard_variants_match():
    assert match_notorious("Charizard ex") == "Charizard"
    assert match_notorious("Dark Charizard") == "Charizard"
    assert match_notorious("Mega Charizard EX (101/108)") == "Charizard"
    assert match_notorious("charizard vmax") == "Charizard"  # case-insensitive


def test_charizardite_does_not_match():
    # "Charizardite X" é um ITEM (Mega Stone), não o Pokémon.
    assert match_notorious("Charizardite X") is None
    assert not is_notorious("Charizardite Y")


def test_mew_vs_mewtwo_word_boundary():
    # "Mew" não pode casar DENTRO de "Mewtwo"; Mewtwo tem entrada própria
    # e o matcher prefere o nome mais longo.
    assert match_notorious("Mewtwo VSTAR") == "Mewtwo"
    assert match_notorious("Mew ex") == "Mew"


def test_prefix_forms_match():
    assert match_notorious("Mega Gengar ex") == "Gengar"
    assert match_notorious("Umbreon VMAX (Alternate Art)") == "Umbreon"
    assert match_notorious("Radiant Greninja") == "Greninja"


def test_eevee_not_eeveelution_word():
    assert match_notorious("Eevee") == "Eevee"
    # palavra "Eeveelution" não é a carta do Eevee
    assert match_notorious("Eeveelution Fan Box") is None


def test_non_notorious_returns_none():
    assert match_notorious("Paldean Wooper - 221/193") is None
    assert match_notorious("Milcery") is None
    assert match_notorious("") is None
    assert match_notorious(None) is None
