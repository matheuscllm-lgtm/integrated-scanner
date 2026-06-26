"""Registro de sets COMPARTILHADO — o coração da varredura coordenada.

Problema que isto resolve (pedido do operador 2026-06-21): "quando rodar o scan
integrado, rodar o scan de maneira integrada DENTRO DOS SETS solicitados". Antes,
cada fonte tinha a sua própria lista de sets HARDCODED, e elas NÃO coincidiam (o
CT varria 8 sets SV, o MYP varria 11 incluindo era ME, a Liga dependia de um CSV
qualquer). Resultado: a "tabela unificada" misturava sets diferentes por fonte.

A solução é um identificador CANÔNICO por set (o código OFICIAL do set, estilo
Liga: PRE, SSP, SCR...) e um mapa que traduz esse código pra convenção de CADA
fonte. Assim `--sets PRE,SSP` faz os 4 scanners varrerem EXATAMENTE Prismatic
Evolutions e Surging Sparks, cada um na sua linguagem.

═══════════════════════════════════════════════════════════════════════════════
As 4 convenções de nomenclatura de set (verificadas no código de cada repo):
  - Liga : código OFICIAL do set, MAIÚSCULO ("PRE", "SSP"). É a nossa chave.
  - MYP  : SUBSTRING do título EN da edição ("Prismatic", "Surging Sparks").
           ⚠️ É substring, não código — guardamos a string EXATA e TESTADA aqui
           (nunca deduzir do nome: aliases deduzidos por LLM já deram errado —
           lição do ASI-Evolve). Os testes travam que to_myp_editions("quick")
           reproduz a lista hardcoded antiga byte a byte.
  - CT   : código próprio minúsculo do CardTrader ("pre", "ssp", "sv8pt5"...).
  - COMC : scaneia por ERA (recent/middle/vintage), mas aceita um allowlist
           `--sets <abbrev>` que filtra DENTRO da era. Por isso o mapa COMC é
           um par (era, abbrev): pra varrer um set, passamos a era dele + o
           abbrev no allowlist.
═══════════════════════════════════════════════════════════════════════════════

Era Mega Evolution (ASH/PFO/CHR) é caso especial e DELIBERADO:
  - Não tem código oficial consolidado como os SV → usamos rótulos INTERNOS
    (ASH/PFO/CHR) como chave canônica (documentado, não é "código oficial").
  - Liga e COMC NÃO cobrem ME (sem entrada no ED_SETS da Liga / sem slug no
    comc_set_slugs.json) → liga=None, comc=None.
  - pokemontcg.io tem 0% de preço TCG REAL na era ME (medido — `me*` retorna 200
    mas sem `prices`); como TANTO o CT quanto o MYP usam essa fonte de preço, o
    CT também só pegaria fallback estat lá. Hoje o quick do CT já NÃO varre ME
    (só o MYP varre, e o operador pediu ME no MYP). Então ME = **só MYP**:
    ct=None pros sets ME. Eles pulam CT/Liga/COMC COM NOTA no status (honesto).

Tudo aqui é FUNÇÃO PURA (sem rede, sem subprocess) → testável offline.
NÃO toca em threshold, FX, nem edita os repos-fonte (o integrado é orquestrador).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Eras do COMC (espelho de scanner-comc/config.py VALID_ERAS). SV/ME são 2023+
# → todos caem em "recent" (cutoffs: vintage≤2010, middle≤2019).
COMC_ERA_RECENT = "recent"


@dataclass(frozen=True)
class SetEntry:
    """Um set e como CADA fonte o nomeia. Campo None = fonte não cobre o set."""
    canonical: str          # chave canônica (código oficial, ou rótulo interno p/ ME)
    name: str               # nome legível EN (casa o set_name do CSV da Liga)
    era: str                # "SV" | "ME" | "SWSH" (informativo)
    liga: Optional[str]     # código de set da Liga (== canonical p/ SV), None se ausente
    myp: Optional[str]      # SUBSTRING EXATA do título MYP (testada), None se ausente
    ct: Optional[str]       # código de expansão do CardTrader, None se ausente
    comc: Optional[tuple[str, str]]  # (era, abbrev) p/ o allowlist do COMC, None se ausente


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRO CANÔNICO. Ordem dentro de cada era = ordem das listas quick antigas
# (pra reprodução byte-a-byte). Adicionar set novo = uma linha aqui.
#
# As substrings MYP refletem EXATAMENTE a MYP_QUICK_EDITIONS antiga: "Surging"
# (não "Surging Sparks"), "Journey" (não "Journey Together"), "Twilight",
# "Shrouded" — curtas DE PROPÓSITO (já testadas em produção). "Paldean Fates" e
# "151" são as exatas também. NÃO encurtar/alongar sem re-testar contra o MYP.
# ═══════════════════════════════════════════════════════════════════════════════
_REGISTRY: list[SetEntry] = [
    # ── Scarlet & Violet (cobertas pelas 4 fontes) ────────────────────────────
    SetEntry("PRE", "Prismatic Evolutions", "SV", "PRE", "Prismatic",     "pre", (COMC_ERA_RECENT, "PRE")),
    SetEntry("SSP", "Surging Sparks",       "SV", "SSP", "Surging",       "ssp", (COMC_ERA_RECENT, "SSP")),
    SetEntry("JTG", "Journey Together",     "SV", "JTG", "Journey",       "jtg", (COMC_ERA_RECENT, "JTG")),
    SetEntry("SCR", "Stellar Crown",        "SV", "SCR", "Stellar",       "scr", (COMC_ERA_RECENT, "SCR")),
    SetEntry("TWM", "Twilight Masquerade",  "SV", "TWM", "Twilight",      "twm", (COMC_ERA_RECENT, "TWM")),
    SetEntry("SFA", "Shrouded Fable",       "SV", "SFA", "Shrouded",      "sfa", (COMC_ERA_RECENT, "SFA")),
    SetEntry("PAF", "Paldean Fates",        "SV", "PAF", "Paldean Fates", "paf", (COMC_ERA_RECENT, "PAF")),
    SetEntry("MEW", "151",                  "SV", "MEW", "151",           "mew", (COMC_ERA_RECENT, "MEW")),
    # SV adicionais conhecidos (fora do quick, mas escopo livre --sets pode pedir)
    SetEntry("DRI", "Destined Rivals",      "SV", "DRI", "Destined Rivals", "dri", (COMC_ERA_RECENT, "DRI")),
    SetEntry("TEF", "Temporal Forces",      "SV", "TEF", "Temporal Forces", "tef", (COMC_ERA_RECENT, "TEF")),
    SetEntry("PAR", "Paradox Rift",         "SV", "PAR", "Paradox Rift",    "par", (COMC_ERA_RECENT, "PAR")),
    SetEntry("OBF", "Obsidian Flames",      "SV", "OBF", "Obsidian Flames", "sv3", (COMC_ERA_RECENT, "OBF")),
    SetEntry("PAL", "Paldea Evolved",       "SV", "PAL", "Paldea Evolved",  "sv2", (COMC_ERA_RECENT, "PAL")),
    # ── Sword & Shield: os 4 sets mais recentes da era SWSH (fecham os "20").
    #   CT: código VERIFICADO via API /expansions (lorg/sit/crz/astr).
    #   Liga: LOR e STB constam no alias map de normalização; CRZ/ASR ausentes → None.
    #   COMC: sem slug p/ nenhum em comc_set_slugs.json → comc=None (não cobre).
    #   MYP: nome canônico EN (mesmo padrão das entradas SV). Subtítulos ÚNICOS →
    #   substring errada = NO-OP inofensivo (casa 0 edições), NUNCA escaneia set
    #   errado (≠ "Scarlet & Violet" base, que colidiria com todos os SV — por isso
    #   o base NÃO entra). Confirmar os títulos no próximo run MYP sem bloqueio CF
    #   (mypcards.com devolveu 403 neste IP de datacenter após o scan pesado de hoje).
    SetEntry("LOR", "Lost Origin",          "SWSH", "LOR", "Lost Origin",     "lorg", None),
    SetEntry("SIT", "Silver Tempest",       "SWSH", "STB", "Silver Tempest",  "sit",  None),
    SetEntry("CRZ", "Crown Zenith",         "SWSH", None,  "Crown Zenith",    "crz",  None),
    SetEntry("ASR", "Astral Radiance",      "SWSH", None,  "Astral Radiance", "astr", None),
    # ── Mega Evolution (SÓ MYP — ver docstring; Liga/CT/COMC = None) ───────────
    SetEntry("ASH", "Ascended Heroes",      "ME", None, "Ascended Heroes",  None, None),
    SetEntry("PFO", "Perfect Order",        "ME", None, "Perfect Order",    None, None),
    SetEntry("CHR", "Chaos Rising",         "ME", None, "Chaos Rising",     None, None),
]

_BY_CANON: dict[str, SetEntry] = {e.canonical: e for e in _REGISTRY}

# Profiles nomeados. Mínimos DE PROPÓSITO (YAGNI): só os 2 que a compat exige.
#   - "quick": reproduz exatamente o escopo quick antigo (8 SV + 3 ME).
#   - "full" : sentinela "tudo" (NÃO é lista de sets; ver resolve_scope/is_full).
# A ORDEM de quick == ordem das constantes antigas (CT_QUICK_SETS / MYP_QUICK).
_PROFILE_QUICK = ["PRE", "SSP", "JTG", "SCR", "TWM", "SFA", "PAF", "MEW",
                  "ASH", "PFO", "CHR"]
PROFILES = {"quick", "full"}

FULL = "__FULL__"  # sentinela retornado por resolve_scope("full")


class UnknownSetError(ValueError):
    """Código de set fora do registro (com dica dos conhecidos)."""


def known_canonicals() -> list[str]:
    return [e.canonical for e in _REGISTRY]


def entries() -> list[SetEntry]:
    """Todas as entradas do registro (cópia rasa — não muta o original).

    Acessor público pra quem precisa do mapa COMPLETO de convenções por set —
    ex.: o cross_source.py, que faz o caminho INVERSO (string de set de uma
    fonte → código canônico) pra casar a mesma carta entre fontes.
    """
    return list(_REGISTRY)


def get_entry(canonical: str) -> Optional[SetEntry]:
    """Entrada pelo código canônico (case-insensitive), ou None se desconhecido."""
    return _BY_CANON.get((canonical or "").strip().upper())


def catalog() -> list[dict]:
    """Catálogo completo de sets pra API/exposição: cada entrada com a chave
    canônica + o nome + era + como CADA fonte cobre (None = fonte não cobre)."""
    out = []
    for e in _REGISTRY:
        out.append({
            "canonical": e.canonical,
            "name": e.name,
            "era": e.era,
            "sources": {
                "liga": e.liga,
                "myp": e.myp,
                "ct": e.ct,
                "comc": {"era": e.comc[0], "abbrev": e.comc[1]} if e.comc else None,
            },
            "covered_by": [s for s, v in
                           (("liga", e.liga), ("myp", e.myp), ("ct", e.ct),
                            ("comc", e.comc)) if v],
        })
    return out


def resolve_scope(spec: str) -> object:
    """Resolve um spec de escopo numa lista de SetEntry (ou no sentinela FULL).

    `spec` pode ser:
      - um profile nomeado: "quick" → lista quick; "full" → FULL (sentinela).
      - uma lista CSV de códigos canônicos: "PRE,SSP" ou "pre, ssp" (case-insens).
    Levanta UnknownSetError se algum código não existe no registro.
    """
    s = (spec or "").strip()
    if s.lower() == "full":
        return FULL
    if s.lower() == "quick":
        return [_BY_CANON[c] for c in _PROFILE_QUICK]
    codes = [c.strip().upper() for c in s.split(",") if c.strip()]
    if not codes:
        raise UnknownSetError("escopo vazio")
    unknown = [c for c in codes if c not in _BY_CANON]
    if unknown:
        raise UnknownSetError(
            f"set(s) desconhecido(s): {', '.join(unknown)}. "
            f"Conhecidos: {', '.join(known_canonicals())} "
            f"(ou os profiles {sorted(PROFILES)}).")
    # dedup preservando ordem
    seen, out = set(), []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(_BY_CANON[c])
    return out


def is_full(scope: object) -> bool:
    return scope is FULL


# ── Tradutores: escopo → convenção de cada fonte ────────────────────────────────
# Cada um devolve (valor_pra_fonte, skipped) onde skipped = lista de canônicos que
# a fonte NÃO cobre (vira nota honesta no status). Em modo FULL, devolvem o
# sinal "tudo" que o orquestrador já sabe traduzir (ver run_integrated).

def to_ct_sets(scope: list[SetEntry]) -> tuple[list[str], list[str]]:
    sets = [e.ct for e in scope if e.ct]
    skipped = [e.canonical for e in scope if not e.ct]
    return sets, skipped


def to_myp_editions(scope: list[SetEntry]) -> tuple[list[str], list[str]]:
    eds = [e.myp for e in scope if e.myp]
    skipped = [e.canonical for e in scope if not e.myp]
    return eds, skipped


def to_liga_codes(scope: list[SetEntry]) -> tuple[list[str], list[str]]:
    codes = [e.liga for e in scope if e.liga]
    skipped = [e.canonical for e in scope if not e.liga]
    return codes, skipped


def to_liga_names(scope: list[SetEntry]) -> list[str]:
    """Nomes EN dos sets do escopo que a Liga cobre — pra checar cobertura do CSV
    (o liga_offers.csv guarda set_name completo, não código)."""
    return [e.name for e in scope if e.liga]


def to_comc(scope: list[SetEntry]) -> tuple[list[tuple[str, list[str]]], list[str]]:
    """Agrupa o escopo por ERA do COMC → [(era, [abbrev...])]. COMC filtra DENTRO
    da era pelo allowlist. Sets sem mapa COMC (ME) entram em skipped."""
    by_era: dict[str, list[str]] = {}
    skipped = []
    for e in scope:
        if e.comc is None:
            skipped.append(e.canonical)
            continue
        era, abbrev = e.comc
        by_era.setdefault(era, []).append(abbrev)
    return list(by_era.items()), skipped
