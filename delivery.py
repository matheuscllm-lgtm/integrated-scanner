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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

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


def filter_deals(deals: list[Deal],
                 min_margin_pct: float = MIN_MARGIN_PCT_DEFAULT,
                 notorious_only: bool = False) -> list[Deal]:
    kept = [d for d in deals if d.margem_pct >= min_margin_pct]
    if notorious_only:
        kept = [d for d in kept if d.notorio]
    kept.sort(key=lambda d: d.margem_pct, reverse=True)
    return kept


def _md_escape(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


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
            f"| {dur} | {out} | {_md_escape(s.detail) or '—'} |")
    lines.append("")
    lines.append(
        f"Corte aplicado: **margem bruta ≥ {min_margin_pct:.0f}%** "
        f"(base = preço de compra; zero taxas — convenção unificada, ver CLAUDE.md). "
        f"FX global usado p/ fontes sem câmbio próprio: **{fx_global:.3f}**."
        + (" Filtro extra: **só Pokémon notórios**." if notorious_only else ""))
    lines.append("")

    # ── Tabela completa ───────────────────────────────────────────────
    lines.append(f"## Deals ({len(deals)} linhas, ordenado por margem bruta desc)")
    lines.append("")
    if not deals:
        lines.append("_Nenhum deal passou o corte._")
        return "\n".join(lines) + "\n"

    lines.append("| " + " | ".join(UNIFIED_COLUMNS) + " |")
    lines.append("|" + "---|" * len(UNIFIED_COLUMNS))
    for d in deals:
        row = d.to_row()
        cells = [_md_escape(_fmt(row[c])) for c in UNIFIED_COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("_Valorização = heurística 0-100 (raridade + idade do set + "
                 "preço-âncora) — sem série histórica; não é previsão. "
                 "Decisão de compra é do operador._")
    return "\n".join(lines) + "\n"


def write_xlsx(deals: list[Deal], path: Path) -> None:
    """xlsx local de APOIO (a entrega oficial é a tabela markdown no chat)."""
    import pandas as pd
    df = pd.DataFrame([d.to_row() for d in deals], columns=UNIFIED_COLUMNS)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False)
