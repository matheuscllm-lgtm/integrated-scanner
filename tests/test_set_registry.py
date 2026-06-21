"""Testes do registro de sets compartilhado (varredura coordenada).

Trava o contrato que a varredura coordenada depende:
  - o profile "quick" reproduz BYTE A BYTE as listas hardcoded antigas (CT/MYP)
    — garantia de não-regressão pros 29 testes e pra memória do operador;
  - era ME (ASH/PFO/CHR) pula Liga/CT/COMC com a fonte marcada em "skipped";
  - tradutores devolvem a convenção certa de cada fonte (CT minúsculo, MYP
    substring exata, Liga código, COMC (era, allowlist));
  - escopo livre é case-insensitive, dedupa e rejeita código desconhecido.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from set_registry import (FULL, UnknownSetError, is_full, resolve_scope, to_comc,
                          to_ct_sets, to_liga_codes, to_liga_names,
                          to_myp_editions)

HERE = Path(__file__).resolve().parent.parent

# As listas LEGADAS que a varredura coordenada tem que reproduzir no "quick".
# Copiadas literais do run_integrated.py PRÉ-registry (CT_QUICK_SETS /
# MYP_QUICK_EDITIONS). Se um destes mudar, é decisão consciente — atualize aqui.
LEGACY_CT_QUICK = ["pre", "ssp", "jtg", "scr", "twm", "sfa", "paf", "mew"]
LEGACY_MYP_QUICK = ["Prismatic", "Surging", "Journey", "Stellar", "Twilight",
                    "Shrouded", "Paldean Fates", "151", "Ascended Heroes",
                    "Perfect Order", "Chaos Rising"]


def test_quick_reproduces_legacy_ct_byte_for_byte():
    ct, _ = to_ct_sets(resolve_scope("quick"))
    assert ct == LEGACY_CT_QUICK


def test_quick_reproduces_legacy_myp_byte_for_byte():
    myp, skipped = to_myp_editions(resolve_scope("quick"))
    assert myp == LEGACY_MYP_QUICK
    assert skipped == []  # MYP cobre tudo do quick (inclusive ME)


def test_me_skipped_from_liga_ct_comc_with_note():
    scope = resolve_scope("ASH,PFO,CHR")  # só era ME
    ct, ct_sk = to_ct_sets(scope)
    liga, liga_sk = to_liga_codes(scope)
    comc, comc_sk = to_comc(scope)
    assert ct == [] and set(ct_sk) == {"ASH", "PFO", "CHR"}
    assert liga == [] and set(liga_sk) == {"ASH", "PFO", "CHR"}
    assert comc == [] and set(comc_sk) == {"ASH", "PFO", "CHR"}
    # MYP cobre ME
    myp, myp_sk = to_myp_editions(scope)
    assert myp == ["Ascended Heroes", "Perfect Order", "Chaos Rising"]
    assert myp_sk == []


def test_full_is_sentinel():
    assert is_full(resolve_scope("full"))
    assert resolve_scope("full") is FULL
    assert not is_full(resolve_scope("quick"))


def test_unknown_set_raises():
    with pytest.raises(UnknownSetError):
        resolve_scope("PRE,NOPE")


def test_free_scope_case_insensitive_and_dedup():
    scope = resolve_scope("pre, SSP , pre")  # minúsculo, espaços, duplicado
    assert [e.canonical for e in scope] == ["PRE", "SSP"]


def test_to_comc_groups_by_era_with_allowlist():
    groups, skipped = to_comc(resolve_scope("PRE,SSP"))
    assert groups == [("recent", ["PRE", "SSP"])]
    assert skipped == []


def test_to_liga_names_uses_full_set_name():
    # o liga_offers.csv guarda set_name COMPLETO — a cobertura casa por nome
    names = to_liga_names(resolve_scope("PRE,MEW"))
    assert names == ["Prismatic Evolutions", "151"]


def test_myp_substring_is_exact_short_form():
    # substrings curtas testadas em produção — NÃO os nomes completos
    myp, _ = to_myp_editions(resolve_scope("SSP,JTG,TWM,SFA"))
    assert myp == ["Surging", "Journey", "Twilight", "Shrouded"]


# ── integração no CLI: --sets e --profile são mutuamente exclusivos ──────────
def test_cli_sets_and_profile_mutually_exclusive():
    proc = subprocess.run(
        [sys.executable, str(HERE / "run_integrated.py"),
         "--sets", "PRE", "--profile", "quick", "--skip-scan"],
        cwd=str(HERE), capture_output=True, text=True)
    assert proc.returncode != 0
    assert "mutuamente exclusiv" in (proc.stderr + proc.stdout).lower()


def test_cli_unknown_set_errors():
    proc = subprocess.run(
        [sys.executable, str(HERE / "run_integrated.py"),
         "--sets", "ZZZ", "--skip-scan"],
        cwd=str(HERE), capture_output=True, text=True)
    assert proc.returncode != 0
    assert "desconhecido" in (proc.stderr + proc.stdout).lower()
