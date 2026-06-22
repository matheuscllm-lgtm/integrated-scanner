"""Normalização: lê o output de cada scanner e converte pro schema unificado.

Cada scanner emite um formato próprio (colunas, moeda e convenção de margem
diferentes). Este módulo traduz tudo pra UMA tabela com as mesmas colunas.

DECISÕES DE DESIGN (documentadas porque as fontes divergem):

1. MARGEM BRUTA UNIFICADA = (revenda − compra) / compra, em PERCENT.
   "Revenda" = preço de referência no TCGPlayer; "compra" = preço na fonte.
   Por que recomputar? Cada scanner usa uma base diferente:
     - MYP e Liga dividem pela COMPRA  (lucro sobre o capital investido)
     - CardTrader e COMC dividem pela REVENDA
   Dividir pela compra é a leitura mais intuitiva ("ganho X% sobre o que
   paguei") e é matematicamente ≥ à margem-sobre-revenda — ou seja, nenhum
   deal que passou no threshold de 30% da própria fonte é descartado aqui.

2. FX (câmbio USD→BRL) é EXPLÍCITO por linha (coluna FX):
     - CardTrader: implícito na própria linha (TCG BRL ÷ TCG USD)
     - Liga: coluna exchange_rate do report
     - MYP e COMC: FX global (flag --fx; default = inferido do output mais
       recente do CT, senão 5.20 documentado)

3. VALORIZAÇÃO (0-100): o CardTrader scanner v2.13 já emite o score; pra
   MYP/COMC/Liga replicamos AQUI a MESMA heurística (funções portadas de
   `card-trader-scanner/cardtrader_scanner.py` — crédito no bloco abaixo).
   É heurística de triagem SEM série histórica de preços; a nota de cada
   linha explica os componentes. Pokémon notório NÃO infla o score — vira
   flag explícito (coluna Notório) e nota.

4. NM-only é invariante das próprias fontes (cada scanner já filtra NM);
   aqui apenas registramos a condição quando a fonte informa.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from notorious import match_notorious

FX_FALLBACK = 5.20  # último recurso, documentado; prefira --fx ou inferência CT

UNIFIED_COLUMNS = [
    "Fonte", "Carta", "Set", "Nº", "Raridade", "Chase Tier", "Notório",
    "Compra (R$)", "Compra (US$)", "FX", "Ref TCG (R$)", "Ref TCG (US$)",
    "Margem bruta %", "Lucro (R$)", "Qtd",
    "Notas", "Link oferta", "Link TCG",
]


@dataclass
class Deal:
    fonte: str
    carta: str
    set_name: str = ""
    numero: str = ""
    raridade: str = ""
    chase_tier: str = ""
    notorio: str = ""            # "⭐ <nome>" ou ""
    compra_brl: float = 0.0
    compra_usd: float = 0.0
    fx: float = 0.0
    ref_brl: float = 0.0
    ref_usd: float = 0.0
    margem_pct: float = 0.0      # percent, base = compra (ver docstring)
    lucro_brl: float = 0.0
    qtd: Optional[int] = None    # None = fonte não informa
    valorizacao: Optional[int] = None
    notas: list[str] = field(default_factory=list)
    link_oferta: str = ""
    link_tcg: str = ""

    def to_row(self) -> dict[str, Any]:
        return {
            "Fonte": self.fonte,
            "Carta": self.carta,
            "Set": self.set_name,
            "Nº": self.numero,
            "Raridade": self.raridade,
            "Chase Tier": self.chase_tier,
            "Notório": self.notorio,
            "Compra (R$)": round(self.compra_brl, 2),
            "Compra (US$)": round(self.compra_usd, 2),
            "FX": round(self.fx, 3) if self.fx else "",
            "Ref TCG (R$)": round(self.ref_brl, 2),
            "Ref TCG (US$)": round(self.ref_usd, 2),
            "Margem bruta %": round(self.margem_pct, 1),
            "Lucro (R$)": round(self.lucro_brl, 2),
            "Qtd": self.qtd if self.qtd is not None else "—",
            "Notas": "; ".join(self.notas),
            "Link oferta": self.link_oferta,
            "Link TCG": self.link_tcg,
        }


def _num(value: Any, default: float = 0.0) -> float:
    """Converte célula pra float, tolerando NaN/None/string."""
    if value is None:
        return default
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(f):
        return default
    return f


def _clean_str(value: Any) -> str:
    """Célula → str, com NaN do pandas (célula vazia) virando ""."""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    s = str(value).strip()
    return "" if s.lower() == "nan" else s


def gross_margin_pct(ref_brl: float, compra_brl: float) -> float:
    """Margem bruta unificada: (revenda − compra)/compra ×100. Zero taxas."""
    if compra_brl <= 0:
        return 0.0
    return (ref_brl - compra_brl) / compra_brl * 100.0


def _flag_notorious(deal: Deal) -> None:
    hit = match_notorious(deal.carta)
    if hit:
        deal.notorio = f"⭐ {hit}"
        deal.notas.append("⭐ Pokémon notório (ícone de demanda histórica)")


# ══════════════════════════════════════════════════════════════════════
# VALORIZAÇÃO — heurística PORTADA de card-trader-scanner v2.13
# (cardtrader_scanner.py: CHASE_TIER_PATTERNS, classify_chase_tier,
#  _valorization_age_component, compute_valorization). Mesmos pesos e notas,
# pra que o score de MYP/COMC/Liga seja comparável ao que o CT já emite.
# Honestidade: SEM série histórica de preços — é triagem, não previsão.
# ══════════════════════════════════════════════════════════════════════
CHASE_TIER_PATTERNS = {
    "TOP": [
        "special illustration rare", "sir", "illustration rare",
        "special art rare", "sar", "hyper rare", "ultra hyper rare",
        "secret rare", "rara secreta",
    ],
    "MID": [
        "full art", "alt art", "alternate art", "alternative art",
        "rainbow rare", "gold rare", "trainer gallery", "double rare",
        "rara hiper", "ultra rare",
    ],
    "MODEST": [
        "holo rare", "reverse holo", "reverse foil", "promo",
        "rare holo",
    ],
    "BULK": [
        "common", "comum", "uncommon", "incomum",
    ],
}


def classify_chase_tier(rarity: Optional[str]) -> str:
    """Portado do CT scanner: TOP/MID/MODEST/BULK a partir da raridade."""
    if not rarity:
        return ""
    r = str(rarity).lower().strip()
    for tier, patterns in CHASE_TIER_PATTERNS.items():
        if any(p in r for p in patterns):
            return tier
    return "MODEST"  # raridade presente mas não mapeada → conservador


def _valorization_age_component(set_release_date: Optional[str],
                                now: Optional[datetime] = None) -> tuple[int, str]:
    """Portado do CT scanner: componente de maturidade do set (0-35)."""
    if not set_release_date:
        return 10, "idade do set desconhecida (sem data na fonte)"
    now = now or datetime.now()
    parsed = None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(set_release_date, fmt)
            break
        except (ValueError, TypeError):
            continue
    if parsed is None:
        return 10, "idade do set desconhecida (data ilegível)"
    age_years = (now - parsed).days / 365.25
    if age_years < 0.5:
        return 12, f"set recém-lançado (~{age_years:.1f} anos) — preço ainda instável"
    if age_years < 1.5:
        return 22, f"set jovem (~{age_years:.1f} anos) — saindo do dip pós-lançamento"
    if age_years <= 4.0:
        return 35, f"set maduro (~{age_years:.1f} anos) — janela clássica de valorização"
    if age_years <= 6.0:
        return 24, f"set antigo (~{age_years:.1f} anos) — fora de circulação, demanda residual"
    return 16, f"set muito antigo (~{age_years:.1f} anos) — vintage, líquido só em chase"


def compute_valorization(rarity: Optional[str],
                         set_release_date: Optional[str],
                         tcg_market_usd: float,
                         now: Optional[datetime] = None) -> tuple[int, str]:
    """Portado do CT scanner v2.13: score 0-100 + nota explicativa."""
    tier = classify_chase_tier(rarity)
    rarity_pts = {"TOP": 45, "MID": 30, "MODEST": 12, "BULK": 0}.get(tier, 8)
    rarity_note = {
        "TOP": "raridade top (chase forte)",
        "MID": "raridade média-alta (alt/ultra/rainbow)",
        "MODEST": "raridade modesta (holo/promo)",
        "BULK": "bulk (common/uncommon — baixo potencial)",
    }.get(tier, "raridade desconhecida")
    age_pts, age_note = _valorization_age_component(set_release_date, now=now)
    if tcg_market_usd < 15:
        price_pts, price_note = 4, "preço-âncora baixo (<$15)"
    elif tcg_market_usd < 40:
        price_pts, price_note = 10, "preço-âncora médio ($15-40)"
    elif tcg_market_usd < 100:
        price_pts, price_note = 16, "preço-âncora alto ($40-100)"
    else:
        price_pts, price_note = 20, "preço-âncora premium (>$100)"
    score = rarity_pts + age_pts + price_pts
    note = f"{rarity_note}; {age_note}; {price_note} (heurística — sem série histórica)"
    return score, note


# ══════════════════════════════════════════════════════════════════════
# ROW MAPPERS — um por fonte. Recebem a linha como dict (testável sem xlsx).
# ══════════════════════════════════════════════════════════════════════

def _col(row: dict[str, Any], *candidates: str) -> Any:
    """Acha a primeira coluna cujo nome contém o trecho pedido (tolerante a
    acento/mojibake — outputs antigos podem ter encoding variado)."""
    for cand in candidates:
        if cand in row:
            return row[cand]
    low = {str(k).lower(): v for k, v in row.items()}
    for cand in candidates:
        c = cand.lower()
        for k, v in low.items():
            if c in k:
                return v
    return None


def ct_row_to_deal(row: dict[str, Any], fx_global: float) -> Deal:
    """CardTrader chase_*.xlsx (33 colunas, v2.13). Margens da fonte vêm em
    FRAÇÃO e base=revenda; aqui recomputamos dos preços brutos."""
    ref_brl = _num(_col(row, "TCG Market (BRL)"))
    ref_usd = _num(_col(row, "TCG Market (USD)"))
    live = _num(_col(row, "LIVE R$ (real)"))
    compra_brl = live if live > 0 else _num(_col(row, "Scan R$ (raw)"))
    fx = ref_brl / ref_usd if ref_usd > 0 else fx_global
    deal = Deal(
        fonte="CardTrader",
        carta=str(_col(row, "Card Name") or ""),
        set_name=str(_col(row, "Set") or ""),
        numero=str(_col(row, "Nº", "N°") or ""),
        raridade=str(_col(row, "Rarity") or ""),
        chase_tier=str(_col(row, "Chase Tier") or ""),
        compra_brl=compra_brl,
        compra_usd=compra_brl / fx if fx else 0.0,
        fx=fx,
        ref_brl=ref_brl,
        ref_usd=ref_usd,
        margem_pct=gross_margin_pct(ref_brl, compra_brl),
        lucro_brl=ref_brl - compra_brl,
        qtd=int(_num(_col(row, "Qtd"), 0)) or None,
        link_oferta=str(_col(row, "Link CardTrader") or ""),
        link_tcg=str(_col(row, "Link TCG") or ""),
    )
    val = _col(row, "Valorização (0-100)", "Valoriza")
    if val is not None and not (isinstance(val, float) and math.isnan(val)):
        deal.valorizacao = int(_num(val))
    val_notes = _col(row, "Valorização — Notas")
    if val_notes and str(val_notes) != "nan":
        deal.notas.append(str(val_notes))
    status = _col(row, "Validation Status")
    if status and str(status) != "nan":
        deal.notas.append(f"validação CT: {status}")
    _flag_notorious(deal)
    return deal


_MYP_NUMBER_RE = re.compile(r"\((\d+[a-zA-Z]?)\s*/\s*\d+\)\s*$")

# O catálogo do MYP concatena nome PT + nome EN da edição SEM separador
# ("Escarlate e Violeta: Máscaras do CrepúsculoSV06: Twilight Masquerade").
# Pra display unificado mantemos o lado EN (consistente com CT/COMC).
# Boundary conservador: só divide quando o lado direito começa com um
# prefixo de era EN conhecido — título EN-only ou vintage fica intacto.
# NÃO mexer no Edition cru do MYP (é load-bearing no filtro --editions e no
# mapa de setcodes de lá); isto é só cosmético da tabela unificada.
_MYP_EDITION_EN_BOUNDARY = re.compile(
    r"(?<=[a-záéíóúâêôãõàçü0-9!?.)])"
    r"(?=(?:SV\d|ME[\d:]|SM\d|SWSH\d|XY\d"
    r"|Scarlet & Violet|Sword & Shield|Sun & Moon|Mega Evolution|Pokémon GO))")

_TCG_SEARCH_BASE = "https://www.tcgplayer.com/search/pokemon/product?productLineName=pokemon&q="


def clean_myp_edition(title: str) -> str:
    """Lado EN do título de edição bilíngue concatenado do MYP (display)."""
    title = title or ""
    m = _MYP_EDITION_EN_BOUNDARY.search(title)
    return title[m.start():].strip() if m else title


def _myp_tcg_search_fallback(card_name: str) -> str:
    """URL de busca TCGplayer pelo nome (mesma lógica do tcg_search_url do
    MYP) — fallback pra XLSX antigo sem a coluna 'TCG URL' (pré-v5.11.2)."""
    from urllib.parse import quote_plus
    base = re.sub(r"\s*\([^)]*\)\s*$", "", card_name or "").strip()
    return _TCG_SEARCH_BASE + quote_plus(base) if base else ""


def myp_row_to_deal(row: dict[str, Any], fx_global: float) -> Deal:
    """MYP results/*.xlsx (15 colunas, v5.11). Preços já em BRL; 'Margin %'
    da fonte é FRAÇÃO base=compra — recomputamos mesmo assim (uniformidade).
    Atenção conhecida: raridade do MYP é pouco confiável (SIR/HR podem vir
    como 'Comum') — fica em nota."""
    name_raw = str(_col(row, "Card Name") or "")
    m = _MYP_NUMBER_RE.search(name_raw)
    numero = m.group(1) if m else ""
    carta = _MYP_NUMBER_RE.sub("", name_raw).strip()
    compra_brl = _num(_col(row, "MYP EN NM (R$)"))
    ref_brl = _num(_col(row, "TCG Player (R$)"))
    fx = fx_global
    rarity = str(_col(row, "Rarity") or "")
    # Honestidade (espelha MYP v5.14.3): o preço TCG do MYP pode ser REAL
    # (pokemontcg.io) ou FALLBACK (`.estat-tcg`, uma estimativa do próprio MYP).
    # O fallback às vezes mapeia a carta errada e infla o "preço TCG" → margem
    # ILUSÓRIA (ex.: Darumaka R$2867 vs R$60). Fonte canônica = coluna
    # "TCG Source"; XLSX antigo (pré-v5.14) infere por "TCG US$" (que só o preço
    # real preenche). Um fallback tem de ir FLAGADO, nunca silencioso.
    _tcg_src = str(_col(row, "TCG Source") or "").strip()
    tcg_is_real = ("pokemontcg" in _tcg_src.lower()) if _tcg_src \
        else _num(_col(row, "TCG US$")) > 0
    ref_usd = ref_brl / fx if fx else 0.0
    score, note = compute_valorization(rarity, None, ref_usd)
    deal = Deal(
        fonte="MYP",
        carta=carta,
        set_name=clean_myp_edition(str(_col(row, "Edition") or "")),
        numero=numero,
        raridade=rarity,
        chase_tier=classify_chase_tier(rarity),
        compra_brl=compra_brl,
        compra_usd=compra_brl / fx if fx else 0.0,
        fx=fx,
        ref_brl=ref_brl,
        ref_usd=ref_usd,
        margem_pct=gross_margin_pct(ref_brl, compra_brl),
        lucro_brl=ref_brl - compra_brl,
        qtd=None,  # MYP não informa estoque da oferta mais barata
        valorizacao=score,
        link_oferta=str(_col(row, "URL") or ""),
        # v5.11.2 do MYP exporta "TCG URL" (texto plano); XLSX antigo não
        # tem a coluna → fallback de busca por nome (sem duplicar setcodes).
        link_tcg=_clean_str(_col(row, "TCG URL")) or _myp_tcg_search_fallback(carta),
    )
    if not tcg_is_real:
        # Nota em PRIMEIRO lugar (insert(0)) — é a ressalva mais importante:
        # a margem desta linha vem de um preço ESTIMADO, pode ser ilusória.
        deal.notas.insert(0, "⚠️ MARGEM NÃO-CONFIÁVEL: preço TCG é FALLBACK "
                             "(`.estat-tcg`, estimativa do MYP — NÃO é o preço real "
                             "do TCGplayer); pode estar inflado → validar no Link TCG "
                             "ou re-rodar o MYP local (myp_enrich.py) antes de operar")
    deal.notas.append(note)
    deal.notas.append("raridade MYP pouco confiável (SIR/HR podem vir 'Comum')")
    sellers = _num(_col(row, "NM Sellers"))
    if sellers:
        deal.notas.append(f"{int(sellers)} sellers NM")
    for warn in ("⚠️ EN Trunc", "⚠️ TCG Suspect", "⚠️ Single Seller", "⚠️ COLLECTOR#"):
        v = _col(row, warn)
        if v is not None and str(v) not in ("", "nan", "NaN"):
            label = warn.replace("⚠️ ", "")
            value = str(v).replace("⚠️", "").strip()
            deal.notas.append(f"alerta {label}: {value}")
    _flag_notorious(deal)
    return deal


def comc_row_to_deal(row: dict[str, Any], fx_global: float) -> Deal:
    """COMC results/comc_deals_*.csv (19 colunas). Preços em USD; margin_pct
    da fonte é PERCENT base=revenda — recomputamos (uniformidade)."""
    compra_usd = _num(_col(row, "comc_price"))
    ref_usd = _num(_col(row, "tcg_reference"))
    fx = fx_global
    compra_brl = compra_usd * fx
    ref_brl = ref_usd * fx
    rarity = str(_col(row, "rarity") or "")
    name_raw = str(_col(row, "card") or "")
    carta = re.sub(r"\s*-\s*\d+[a-zA-Z]?/\d+\s*$", "", name_raw).strip()
    score, note = compute_valorization(rarity, None, ref_usd)
    deal = Deal(
        fonte="COMC",
        carta=carta or name_raw,
        set_name=str(_col(row, "set") or ""),
        numero=str(_col(row, "number") or ""),
        raridade=rarity,
        chase_tier=classify_chase_tier(rarity),
        compra_brl=compra_brl,
        compra_usd=compra_usd,
        fx=fx,
        ref_brl=ref_brl,
        ref_usd=ref_usd,
        margem_pct=gross_margin_pct(ref_brl, compra_brl),
        lucro_brl=ref_brl - compra_brl,
        qtd=int(_num(_col(row, "quantity"), 0)) or None,
        valorizacao=score,
        link_oferta=str(_col(row, "comc_url") or ""),
        link_tcg=str(_col(row, "tcg_url") or ""),
    )
    deal.notas.append(note)
    cond = _col(row, "condition")
    if cond and str(cond) != "nan":
        deal.notas.append(f"condição {cond}")
    conf = _num(_col(row, "confidence"))
    if conf:
        deal.notas.append(f"match conf {conf:.2f}")
    _flag_notorious(deal)
    return deal


def liga_row_to_deal(row: dict[str, Any], fx_global: float) -> Deal:
    """Liga reports/report_*.json. margin_percent da fonte é PERCENT
    base=compra; exchange_rate explícito por linha. Sem raridade/Qtd."""
    compra_brl = _num(_col(row, "price_liga_brl"))
    ref_brl = _num(_col(row, "price_tcg_brl"))
    ref_usd = _num(_col(row, "price_tcg_usd"))
    fx = _num(_col(row, "exchange_rate")) or fx_global
    score, note = compute_valorization(None, None, ref_usd)
    deal = Deal(
        fonte="Liga",
        carta=str(_col(row, "card_name") or ""),
        set_name=str(_col(row, "set_name") or ""),
        compra_brl=compra_brl,
        compra_usd=compra_brl / fx if fx else 0.0,
        fx=fx,
        ref_brl=ref_brl,
        ref_usd=ref_usd,
        margem_pct=gross_margin_pct(ref_brl, compra_brl),
        lucro_brl=ref_brl - compra_brl,
        qtd=None,
        valorizacao=score,
        link_oferta=str(_col(row, "liga_url") or ""),
        link_tcg=str(_col(row, "tcg_url") or ""),
    )
    deal.notas.append(note)
    deal.notas.append("Liga sem raridade no output — score só por preço-âncora")
    _flag_notorious(deal)
    return deal


# ══════════════════════════════════════════════════════════════════════
# FILE READERS — descobrem e leem o output mais recente de cada fonte.
# ══════════════════════════════════════════════════════════════════════

def _resolve_base() -> Path:
    """Onde moram os repos das fontes (irmãos do integrated-scanner).

    - Máquina Windows do operador: `C:\\Users\\mathe` (layout canônico).
    - Sessão Claude Code na nuvem / outra máquina: os repos são clonados como
      IRMÃOS deste repo (ex.: /home/user/integrated-scanner + /home/user/myp-...).
    Override explícito via env `SCANNERS_BASE`. Preserva o comportamento
    Windows (o caminho existe lá) e funciona no container sem editar nada."""
    env = os.environ.get("SCANNERS_BASE")
    if env:
        return Path(env)
    win = Path(r"C:\Users\mathe")
    if win.exists():
        return win
    return Path(__file__).resolve().parent.parent


def _resolve_repo(base: Path, *names: str) -> Path:
    """Primeiro nome de pasta que existe sob `base`; senão o primeiro (default).

    `names` aceita aliases porque o nome local do repo pode divergir do nome no
    GitHub (ex.: Liga = `liga-pokemon-scanner` local vs `liga-cards-scanner` clone)."""
    for n in names:
        cand = base / n
        if cand.exists():
            return cand
    return base / names[0]


_BASE = _resolve_base()
REPOS = {
    "ct": _resolve_repo(_BASE, "card-trader-scanner"),
    "myp": _resolve_repo(_BASE, "myp-arbitrage-scanner"),
    "comc": _resolve_repo(_BASE, "scanner-comc"),
    "liga": _resolve_repo(_BASE, "liga-pokemon-scanner", "liga-cards-scanner"),
}


def latest_ct_output(repo: Path = REPOS["ct"]) -> Optional[Path]:
    """xlsx RAW mais recente (ignora *_post.xlsx, que é o relatório CT)."""
    candidates = [p for p in (repo / "outputs").glob("*.xlsx")
                  if "_post" not in p.stem]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def latest_myp_output(repo: Path = REPOS["myp"]) -> Optional[Path]:
    candidates = list((repo / "results").glob("*.xlsx"))
    candidates += list(repo.glob("myp_arbitrage_*.xlsx"))
    candidates = [p for p in candidates if not p.name.endswith(".bak")]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def latest_comc_outputs(repo: Path = REPOS["comc"]) -> list[Path]:
    """COMC mantém um *_latest.csv por era (recent/vintage); pega os não-vazios."""
    out = []
    for era in ("recent", "vintage"):
        p = repo / "results" / f"comc_deals_{era}_latest.csv"
        if p.exists() and p.stat().st_size > 0:
            out.append(p)
    return out


def comc_run_summaries(repo: Path = REPOS["comc"]) -> dict[str, dict]:
    """Sidecar JSON por era (results/comc_deals_{era}_latest.json).

    É a MARCA de run bem-sucedido do COMC: um scan que terminou com 0 deals
    gera CSV de 0 bytes (que latest_comc_outputs descarta) mas o JSON traz
    {'era', 'generated_utc', 'count': 0, ...}. Distingue "rodou e achou 0"
    de "nunca rodou/sem output". Tolerante a JSON ilegível (era ignorada)."""
    import json
    out: dict[str, dict] = {}
    for era in ("recent", "vintage"):
        p = repo / "results" / f"comc_deals_{era}_latest.json"
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
        if isinstance(data, dict) and "count" in data:
            out[era] = data
    return out


def read_ct(path: Path, fx_global: float) -> list[Deal]:
    import pandas as pd
    df = pd.read_excel(path)
    return [ct_row_to_deal(row, fx_global) for row in df.to_dict("records")]


def read_myp(path: Path, fx_global: float) -> list[Deal]:
    import pandas as pd
    df = pd.read_excel(path)
    return [myp_row_to_deal(row, fx_global) for row in df.to_dict("records")]


def read_comc(path: Path, fx_global: float) -> list[Deal]:
    import pandas as pd
    df = pd.read_csv(path)
    return [comc_row_to_deal(row, fx_global) for row in df.to_dict("records")]


def read_liga(path: Path, fx_global: float) -> list[Deal]:
    """Lê o report da Liga mantendo SÓ as linhas status=="approved".

    O pipeline da Liga já aplica o piso R$50 + margem 30% e marca cada linha
    ("approved"/"rejected"). Ignorar o status deixava carta de centavos
    entrar na tabela unificada com margem absurda (e2e 2026-06-10: Applin
    R$0,08 a "487%" — rejected na fonte, exibida aqui). Piso é invariante
    POR FONTE; o integrado respeita o veredito dela."""
    import json
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [liga_row_to_deal(row, fx_global) for row in rows
            if row.get("status") == "approved"]


def infer_fx_from_ct(repo: Path = REPOS["ct"]) -> Optional[float]:
    """FX implícito no output CT mais recente (mediana de TCG BRL ÷ TCG USD)."""
    path = latest_ct_output(repo)
    if not path:
        return None
    try:
        import pandas as pd
        df = pd.read_excel(path)
        brl = df.get("TCG Market (BRL)")
        usd = df.get("TCG Market (USD)")
        if brl is None or usd is None:
            return None
        ratios = (brl / usd).dropna()
        ratios = ratios[(ratios > 2) & (ratios < 12)]  # sanity
        return float(ratios.median()) if len(ratios) else None
    except Exception:
        return None
