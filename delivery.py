"""Entrega unificada: tabela markdown COMPLETA no chat + xlsx local de apoio.

Regras canônicas do operador (2026-06-06):
- Resultado = tabela markdown no chat com TODOS os deals (nunca amostra curada,
  nunca arquivo por padrão). O xlsx local é só apoio.
- Filtro: margem bruta ≥ 30% e piso de preço (R$50 / $10) — já aplicados pelos
  próprios scanners; aqui re-aplicamos o corte de margem na convenção unificada
  (base = compra; ver normalize.py) e reportamos quantas linhas ficaram de fora.
- Ordenação: margem bruta desc. Coluna Fonte + flags por linha.
- O integrado RANQUEIA e FLAGEIA; NUNCA decide compra — capital é do operador.
"""
from __future__ import annotations

from chat_format import reference_price

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import math
from urllib.parse import quote, urlsplit

from normalize import Deal, UNIFIED_COLUMNS

MIN_MARGIN_PCT_DEFAULT = 30.0  # regra canônica cross-scanner (margem bruta)


@dataclass
class SourceStatus:
    """Status honesto por fonte — vai no cabeçalho da entrega."""
    source: str
    status: str                 # ok | falhou | timeout | pulado | indisponível
    detail: str = ""
    deals_raw: int = 0          # linhas lidas do output da fonte
    deals_kept: int = 0         # linhas que passaram o corte unificado
    duration_s: Optional[float] = None
    output_path: str = ""
    collected_at: str = ""
    mode: str = "scan"


def filter_deals(deals: list[Deal],
                 min_margin_pct: float = MIN_MARGIN_PCT_DEFAULT,
                 notorious_only: bool = False) -> list[Deal]:
    kept = [d for d in deals if d.margem_pct >= min_margin_pct
            and d.compra_brl > 0 and d.ref_brl > 0
            and math.isfinite(d.margem_pct)]
    if notorious_only:
        kept = [d for d in kept if d.notorio]
    kept.sort(key=lambda d: d.margem_pct, reverse=True)
    return kept


def _md_escape(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


# Coluna Links combinada (oferta + TCG numa célula só) — modelo de tabela do MYP,
# padrão cross-scanner (operador 2026-06-19). O XLSX de apoio mantém as 2 colunas
# de URL cruas separadas (write_xlsx usa UNIFIED_COLUMNS); só a ENTREGA combina.
_LINK_COLS = ("Link oferta", "Link TCG")


def _md_links_cell(link_oferta, link_tcg) -> str:
    """'[oferta](url) · [TCG](url)' — só inclui o que existir (http)."""
    parts = []
    of = "" if link_oferta is None else str(link_oferta).strip()
    tc = "" if link_tcg is None else str(link_tcg).strip()
    if of.startswith("http"):
        parts.append(f"[oferta]({quote(of, safe='%/?&=:+,*')})")
    if tc.startswith("http"):
        parts.append(f"[TCG]({quote(tc, safe='%/?&=:+,*')})")
    return " · ".join(parts) if parts else "—"


def bucket_for(deal: Deal, minimum: float = 30.0) -> str:
    if deal.validation_status in {"STALE", "API_ERROR", "PRICE_CHANGED", "rejected"}:
        return "Rejeitados / sem referência"
    if deal.compra_brl <= 0 or deal.ref_brl <= 0:
        return "Rejeitados / sem referência"
    if deal.price_status == "fallback":
        return "Fallback — margem estimada, validar"
    if deal.margem_pct < minimum:
        return "Abaixo do corte — diagnóstico"
    if deal.review_reasons or deal.price_status != "real" or not deal.link_tcg \
            or "/search" in deal.link_tcg:
        return "Validar manualmente"
    return "Deals limpos — referência real"


def supporting_url(deal: Deal) -> str:
    if deal.price_status == "fallback":
        return deal.link_oferta  # estimated price is from MYP's own page
    return "" if "/search" in deal.link_tcg else deal.link_tcg


def build_markdown(deals: list[Deal],
                   statuses: list[SourceStatus],
                   fx_global: float,
                   min_margin_pct: float = MIN_MARGIN_PCT_DEFAULT,
                   notorious_only: bool = False,
                   title: str = "Scanner integrado de singles — entrega unificada") -> str:
    lines: list[str] = [f"# {title}", ""]

    # ── Resumo por fonte ──────────────────────────────────────────────
    lines.append("## Resumo por fonte")
    lines.append("")
    lines.append("| Fonte | Status | Deals lidos | Deals ≥ corte | Duração | Output | Detalhe |")
    lines.append("|---|---|---|---|---|---|---|")
    for s in statuses:
        dur = f"{s.duration_s/60:.1f} min" if s.duration_s else "—"
        out = Path(s.output_path).name if s.output_path else "—"
        lines.append(
            f"| {s.source} | {s.status} | {s.deals_raw} | {s.deals_kept} "
            f"| {dur} | {_md_escape(out)} | {_md_escape('; '.join(filter(None, [s.detail, s.collected_at, s.mode]))) or '—'} |")
    lines.append("")
    lines.append(
        f"Corte aplicado: **margem bruta ≥ {min_margin_pct:.0f}%** "
        f"(base = preço de compra; zero taxas — convenção unificada, ver CLAUDE.md). "
        + (f"FX global usado p/ fontes sem câmbio próprio: **{fx_global:.3f}**." if fx_global > 0 else "FX global indisponível; valores da própria fonte são preservados.")
        + (" Filtro extra: **só Pokémon notórios**." if notorious_only else ""))
    lines.append("")

    lines.append("Referência = preço de mercado da fonte; diferença e margem são brutas, sem taxas.")
    lines.append("Valores de dumps TCGCSV não são cotações em tempo real; data do dump só quando informada pela fonte.")
    real = sum(d.price_status == "real" for d in deals)
    fallback = sum(d.price_status == "fallback" for d in deals)
    lines.append(f"**Cobertura de preço TCG real:** {real}/{len(deals)} linhas; "
                 f"fallback: {fallback}; desconhecida: {len(deals)-real-fallback}.")
    lines.append("")
    if not deals:
        lines.append("_Nenhuma linha disponível nesta execução. Consulte o status das fontes acima; falha não significa ausência de oportunidades._")
        return "\n".join(lines) + "\n"

    buckets = ["Deals limpos — referência real", "Validar manualmente",
               "Fallback — margem estimada, validar", "Rejeitados / sem referência",
               "Abaixo do corte — diagnóstico"]
    for bucket in buckets:
        rows = sorted((d for d in deals if bucket_for(d, min_margin_pct) == bucket),
                      key=lambda d: d.margem_pct, reverse=True)
        if not rows:
            continue
        lines += [f"## {bucket} ({len(rows)})", "",
                  "| # | Fonte | Margem % | Compra R$ | TCG US$ | TCG R$ | Dif R$ | Carta | Set | Raridade | Cond | Qtd | Flags | Links |",
                  "|---|---|---:|---:|---:|---:|---:|---:|---|---|---|---:|---|---|"]
        for i, d in enumerate(rows, 1):
            number = d.numero.strip()
            label = d.carta if not number or number in d.carta else f"{d.carta} {number}"
            has_prices = d.compra_brl > 0 and d.ref_brl > 0
            flags = list(d.review_reasons)
            if d.variant:
                flags.append("variante: " + d.variant)
            if d.price_source:
                flags.append("fonte: " + d.price_source)
            if d.scanned_at:
                flags.append("coleta: " + d.scanned_at)
            if d.notorio:
                flags.append(d.notorio)
            flags.extend(d.notas)
            cells = [str(i), _md_escape(d.fonte),
                     f"{d.margem_pct:.1f}%" if has_prices else "—",
                     f"{d.compra_brl:.2f}" if d.compra_brl > 0 else "—",
                     reference_price(f"{d.ref_usd:.2f}", supporting_url(d)) if d.ref_usd > 0 else "—",
                     reference_price(f"{d.ref_brl:.2f}", supporting_url(d)) if d.ref_brl > 0 else "—",
                     f"{d.ref_brl-d.compra_brl:.2f}" if has_prices else "—",
                     _md_escape(label), _md_escape(d.set_name), _md_escape(d.raridade),
                     _md_escape(d.condition or "—"), str(d.qtd) if d.qtd is not None else "—",
                     _md_escape("; ".join(dict.fromkeys(flags))) or "—",
                     _md_links_cell(d.link_oferta, d.link_tcg)]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines) + "\n"


def build_cross_source_markdown(cards: list,
                                min_margin_pct: float = MIN_MARGIN_PCT_DEFAULT) -> str:
    """Seção 🔀 cross-source: a MESMA carta em ≥2 fontes, preço lado a lado.

    `cards` = saída de cross_source.group_cross_source (lista de CrossSourceCard).
    Aditiva à entrega: NÃO substitui a tabela plana (regra do operador: mostrar
    TODOS os deals). Aqui só destacamos onde a mesma carta aparece em 2+ fontes,
    pra ver onde comprar mais barato. Não decide compra; ranqueia e flagea."""
    from cross_source import SOURCE_ORDER

    lines: list[str] = ["## 🔀 Mesma carta em ≥2 fontes — preço lado a lado", ""]
    if not cards:
        lines.append("_Nenhuma correspondência compatível entre duas ou mais fontes nesta execução._")
        return "\n".join(lines) + "\n"

    lines.append(
        f"Cartas coletadas em **2+ fontes**, com o preço de compra de cada fonte lado a lado (⬅ = mais "
        f"barata). Casamento por **set canônico + número de coleção** (âncora "
        f"forte; nomes divergentes no mesmo número = cartas diferentes, são "
        f"separadas, não viram uma linha enganosa). **`validar`** = casado por "
        f"nome (fonte sem número, ex. Liga) → confira a versão exata. Limitação "
        f"limitada às linhas coletadas: inclui também preços abaixo "
        f"do corte, sem consultar automaticamente todas as lojas. A margem exibida é a da compra mais "
        f"barata. O integrado não decide compra.")
    lines.append("")

    price_cols = [f"{s} R$" for s in SOURCE_ORDER]
    header = (["#", "Carta", "Set", "Nº"] + price_cols
              + ["Mais barata", "Ref TCG R$", "Margem %", "Flag", "Links"])
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))
    for i, c in enumerate(cards, 1):
        cheapest = c.cheapest_deal
        cheap_src = c.cheapest_source
        cells = [str(i), _md_escape(c.display_name or "—"),
                 _md_escape(c.canonical_set), _md_escape(c.display_number or "—")]
        for s in SOURCE_ORDER:
            d = c.deals_by_source.get(s)
            if d is None:
                cells.append("—")
            else:
                mark = " ⬅" if s == cheap_src and not c.validar else ""
                cells.append(f"{d.compra_brl:.2f}{mark}")
        cells.append("validar correspondência" if c.validar else f"{cheap_src} (R${cheapest.compra_brl:.2f})")
        cells.append(reference_price(f"{cheapest.ref_brl:.2f}", supporting_url(cheapest)) if cheapest.ref_brl else "—")
        cells.append(f"{cheapest.margem_pct:.1f}")
        cells.append("validar" if c.validar else "")
        cells.append(_md_links_cell(cheapest.link_oferta, cheapest.link_tcg))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    flagged = [c for c in cards if c.validar]
    if flagged:
        det = "; ".join(
            (f"{c.display_name} {c.display_number}".strip() + f" — {c.motivo}")
            for c in flagged)
        lines.append(f"**`validar`** (casamento a conferir manualmente): {det}")
        lines.append("")
    return "\n".join(lines) + "\n"


def write_xlsx(deals: list[Deal], path: Path) -> None:
    """xlsx local de APOIO (a entrega oficial é a tabela markdown no chat)."""
    import pandas as pd
    df = pd.DataFrame([d.to_row() for d in deals], columns=UNIFIED_COLUMNS)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False)
