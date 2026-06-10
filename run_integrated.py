"""Orquestrador do scanner integrado de singles Pokémon.

Roda os 4 scanners existentes (MYP, CardTrader, COMC, Liga) como SUBPROCESS
caixa-preta — cada um com o PRÓPRIO venv (ambiente Python isolado) e as
PRÓPRIAS flags canônicas — e depois unifica os outputs numa tabela única
(normalize.py → delivery.py). NÃO edita nada dentro dos 4 repos.

ATENÇÃO às convenções de threshold OPOSTAS entre as fontes (armadilha real):
  - CardTrader e COMC: FRAÇÃO  → 0.30  (passar 30 = 3000%, zero deals!)
  - MYP e Liga:        PERCENT → 30
Este orquestrador já passa o valor certo pra cada um; não mexa sem ler isto.

Uso típico:
  python run_integrated.py --profile quick                  # principais sets SV
  python run_integrated.py --skip-scan                      # só re-normaliza outputs existentes
  python run_integrated.py --sources ct,comc --profile quick
  python run_integrated.py --skip-scan --notorious-only

Notas operacionais:
  - Execução SEQUENCIAL (uma fonte por vez). COMC é HEADFUL: abre uma janela
    do Chrome de verdade (necessário pra furar o Cloudflare) — não feche.
  - Falha/timeout de uma fonte NÃO derruba as outras: cada fonte tem timeout
    e log próprios (outputs/logs/), e o status honesto vai no cabeçalho.
  - Liga: roda a partir do data/liga_offers.csv do repo da Liga, gerado
    pelo coletor AO VIVO de lá (src/collect_liga_live.py, headful — rodar
    antes do integrado). Sem o CSV é pulada com aviso. Reports antigos da
    Liga vêm de dados MOCK (demonstração) e NUNCA entram na tabela.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

# Console Windows pode estar em cp1252; a tabela tem ⭐/acentos.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from normalize import (REPOS, FX_FALLBACK, comc_run_summaries, infer_fx_from_ct,
                       latest_ct_output, latest_comc_outputs, latest_myp_output,
                       read_comc, read_ct, read_liga, read_myp)
from delivery import (MIN_MARGIN_PCT_DEFAULT, SourceStatus, build_markdown,
                      filter_deals, write_xlsx)

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "outputs"
LOG_DIR = OUT_DIR / "logs"

VENV_PY = {  # python.exe do venv de CADA repo (caixa-preta: usamos o deles)
    "ct": REPOS["ct"] / ".venv" / "Scripts" / "python.exe",
    "myp": REPOS["myp"] / ".venv" / "Scripts" / "python.exe",
    "comc": REPOS["comc"] / ".venv" / "Scripts" / "python.exe",
    "liga": REPOS["liga"] / ".venv" / "Scripts" / "python.exe",
}

# Sets "principais SV + ME" por fonte (profile quick). Cada fonte nomeia diferente:
CT_QUICK_SETS = ["pre", "ssp", "jtg", "scr", "twm", "sfa", "paf", "mew"]
# MYP --editions é SUBSTRING do título da edição (não alias):
# 2026-06-10 (operador): + Ascended Heroes, Perfect Order e Chaos Rising (era
# Mega Evolution) — são os sets que mais comumente têm bons hits no MYP.
MYP_QUICK_EDITIONS = ["Prismatic", "Surging", "Journey", "Stellar",
                      "Twilight", "Shrouded", "Paldean Fates", "151",
                      "Ascended Heroes", "Perfect Order", "Chaos Rising"]

# Timeouts (segundos) por fonte × profile — generosos mas finitos.
TIMEOUTS = {
    "ct":   {"quick": 45 * 60, "full": 4 * 3600},
    "myp":  {"quick": 2 * 3600, "full": 8 * 3600},   # ~7 min/edição no MYP
    "comc": {"quick": 30 * 60, "full": 75 * 60},     # ~8 min/era + margem
    "liga": {"quick": 15 * 60, "full": 30 * 60},
}

# Idade máxima (horas) do data/liga_offers.csv antes de avisar o operador —
# a coleta da Liga é manual/headful; preços mudam diário, então acima disso
# a margem calculada deixa de ser confiável. AVISO, nunca bloqueio.
LIGA_CSV_MAX_AGE_H = 48.0


def _staleness_warning(mtime: float, now: float | None = None,
                       max_hours: float = LIGA_CSV_MAX_AGE_H) -> str | None:
    """Texto de aviso se o arquivo passou de max_hours; None se fresco."""
    age_h = ((now if now is not None else time.time()) - mtime) / 3600.0
    if age_h <= max_hours:
        return None
    return (f"⚠️ CSV da Liga com {age_h:.0f}h (> {max_hours:.0f}h) — "
            f"considere re-coletar (collect_liga_live.py)")


def _comc_phase2_status(summaries: dict[str, dict]) -> tuple[str, str]:
    """Status honesto do COMC quando não há CSV com deals pra ler.

    O sidecar results/comc_deals_{era}_latest.json com count==0 prova que o
    scan RODOU e terminou sem deals (CSV de 0 bytes é descartado pelo
    latest_comc_outputs) — isso é "ok (0 deals)", não "indisponível"."""
    zero = [(era, s) for era, s in summaries.items() if s.get("count") == 0]
    if zero:
        detail = "; ".join(
            f"{era}: 0 deals (run {s.get('generated_utc', '?')})" for era, s in zero)
        return "ok (0 deals)", detail
    return "indisponível", "nenhum output encontrado"


def _mark_no_output(status_obj) -> None:
    status_obj.status = "indisponível"
    status_obj.detail = "nenhum output encontrado"


def _run_step(name: str, cmd: list[str], cwd: Path, timeout_s: int,
              log_path: Path, env_extra: dict[str, str] | None = None) -> tuple[str, str, float]:
    """Roda um subprocess com log + timeout. Retorna (status, detalhe, duração)."""
    import os
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    if env_extra:
        env.update(env_extra)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[{name}] rodando: {' '.join(str(c) for c in cmd)}")
    print(f"[{name}] log: {log_path}  (timeout {timeout_s//60} min)")
    t0 = time.time()
    try:
        with log_path.open("w", encoding="utf-8", errors="replace") as log:
            proc = subprocess.run(cmd, cwd=str(cwd), env=env, stdout=log,
                                  stderr=subprocess.STDOUT, timeout=timeout_s)
        dur = time.time() - t0
        if proc.returncode == 0:
            return "ok", "", dur
        return "falhou", f"exit code {proc.returncode} (ver log)", dur
    except subprocess.TimeoutExpired:
        return "timeout", f"excedeu {timeout_s//60} min", time.time() - t0
    except FileNotFoundError as exc:
        return "falhou", f"executável não encontrado: {exc}", time.time() - t0


def scan_ct(profile: str, stamp: str, timeout_s: int) -> tuple[str, str, float, Path | None]:
    repo = REPOS["ct"]
    out = repo / "outputs" / f"integrated_{stamp}.xlsx"
    cmd = [str(VENV_PY["ct"]), str(repo / "cardtrader_scanner.py")]
    if profile == "full":
        cmd += ["--all-sets"]
    else:
        cmd += ["--sets", *CT_QUICK_SETS]
    # THRESHOLD EM FRAÇÃO (0.30 = 30%) — convenção do CT, não mudar!
    cmd += ["--threshold", "0.30", "--chase-only", "--validate-top", "30",
            "--max-consecutive-misses", "40", "--output", str(out)]
    status, detail, dur = _run_step("ct", cmd, repo, timeout_s,
                                    LOG_DIR / f"ct_{stamp}.log")
    if status == "ok" and out.exists():
        # postprocess do CT (best-effort): gera o .md/.xlsx no formato CT.
        post = repo / "outputs" / f"integrated_{stamp}_post.xlsx"
        _run_step("ct-post", [str(VENV_PY["ct"]), str(repo / "cardtrader_postprocess.py"),
                              "--input", str(out), "--output", str(post)],
                  repo, 600, LOG_DIR / f"ct_post_{stamp}.log")
        return status, detail, dur, out
    return status, detail, dur, (out if out.exists() else None)


def scan_myp(profile: str, stamp: str, timeout_s: int) -> tuple[str, str, float, Path | None]:
    repo = REPOS["myp"]
    out = repo / "results" / f"integrated_{stamp}.xlsx"
    cmd = [str(VENV_PY["myp"]), str(repo / "myp_arbitrage_scanner.py"),
           # THRESHOLD EM PERCENT INTEIRO (30 = 30%) — convenção do MYP!
           "--threshold", "30", "--min-price", "50", "-o", str(out)]
    if profile == "quick":
        cmd += ["--editions", *MYP_QUICK_EDITIONS]
    status, detail, dur = _run_step("myp", cmd, repo, timeout_s,
                                    LOG_DIR / f"myp_{stamp}.log")
    return status, detail, dur, (out if out.exists() else None)


def scan_comc(profile: str, stamp: str, timeout_s: int) -> tuple[str, str, float, list[Path]]:
    repo = REPOS["comc"]
    eras = ["recent"] if profile == "quick" else ["recent", "vintage"]
    print("[comc] ATENÇÃO: o COMC é HEADFUL — vai abrir uma janela do Chrome "
          "de verdade (necessário pro Cloudflare). Não feche a janela.")
    overall, details, total_dur = "ok", [], 0.0
    for era in eras:
        cmd = [str(VENV_PY["comc"]), "-m", "comc_scanner", "targeted",
               "--era", era, "--fetch-mode", "playwright", "--no-sheets",
               "--restart", "--chase-only"]
        # margem default do COMC já é 0.30 (FRAÇÃO) + piso $10 — canônicos.
        status, detail, dur = _run_step(f"comc-{era}", cmd, repo, timeout_s,
                                        LOG_DIR / f"comc_{era}_{stamp}.log")
        total_dur += dur
        if status != "ok":
            overall = status
            details.append(f"{era}: {detail}")
    outs = latest_comc_outputs(repo)
    return overall, "; ".join(details), total_dur, outs


def scan_liga(profile: str, stamp: str, timeout_s: int) -> tuple[str, str, float, Path | None]:
    """Liga roda a partir do data/liga_offers.csv do repo da Liga.

    O CSV vem do coletor AO VIVO de lá (headful; rodar ANTES do integrado):
      cd C:\\Users\\mathe\\liga-pokemon-scanner
      .venv\\Scripts\\python.exe src\\collect_liga_live.py --sets PRE --no-report
    Não disparamos a coleta daqui de propósito: ela é headful/lenta e o
    operador escolhe os sets; o integrado só consome o CSV mais recente."""
    repo = REPOS["liga"]
    csv_real = repo / "data" / "liga_offers.csv"
    if not csv_real.exists():
        return ("indisponível",
                "sem data/liga_offers.csv; rode o coletor ao vivo no repo da Liga "
                "(src/collect_liga_live.py --sets ... --no-report) e re-rode",
                0.0, None)
    stale = _staleness_warning(csv_real.stat().st_mtime)
    cmd = [str(VENV_PY["liga"]), str(repo / "src" / "main.py")]
    status, detail, dur = _run_step(
        "liga", cmd, repo, timeout_s, LOG_DIR / f"liga_{stamp}.log",
        env_extra={"LIGA_OFFERS_SOURCE": "csv", "LIGA_TCG_SOURCE": "pokemontcg"})
    if stale:  # aviso de CSV velho — nunca bloqueia o run
        detail = f"{stale}; {detail}" if detail else stale
    reports = sorted((repo / "reports").glob("report_*.json"),
                     key=lambda p: p.stat().st_mtime)
    out = reports[-1] if status == "ok" and reports else None
    if out:  # sidecar marcando que ESTE report veio de CSV real (não mock)
        (OUT_DIR / "liga_trusted.json").write_text(
            json.dumps({"report": str(out), "stamp": stamp}), encoding="utf-8")
    return status, detail, dur, out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Scanner integrado de singles Pokémon (MYP+CT+COMC+Liga)")
    ap.add_argument("--profile", choices=["quick", "full"], default="quick",
                    help="quick = principais sets SV; full = catálogo inteiro (HORAS)")
    ap.add_argument("--sources", default="myp,ct,comc,liga",
                    help="fontes, separadas por vírgula (myp,ct,comc,liga)")
    ap.add_argument("--skip-scan", action="store_true",
                    help="NÃO roda scanners; só normaliza os outputs já existentes")
    ap.add_argument("--min-margin", type=float, default=MIN_MARGIN_PCT_DEFAULT,
                    help="corte de margem bruta unificada em PERCENT (default 30)")
    ap.add_argument("--notorious-only", action="store_true",
                    help="só cartas de Pokémon notórios (lista curada)")
    ap.add_argument("--fx", type=float, default=None,
                    help="câmbio USD→BRL p/ fontes sem FX próprio "
                         "(default: inferido do output CT; fallback 5.20)")
    ap.add_argument("--timeout", type=int, default=None,
                    help="sobrescreve o timeout (segundos) de CADA fonte")
    ap.add_argument("--liga-report", type=str, default=None,
                    help="(skip-scan) caminho de um report da Liga vindo de CSV REAL; "
                         "sem isso a Liga é pulada (reports antigos são mock)")
    args = ap.parse_args()

    sources = [s.strip().lower() for s in args.sources.split(",") if s.strip()]
    bad = [s for s in sources if s not in REPOS]
    if bad:
        ap.error(f"fontes desconhecidas: {bad} (válidas: myp, ct, comc, liga)")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    fx_global = args.fx or infer_fx_from_ct() or FX_FALLBACK
    fx_origin = ("--fx" if args.fx else
                 "inferido do output CT" if fx_global != FX_FALLBACK else
                 "fallback documentado")
    print(f"FX global USD→BRL: {fx_global:.3f} ({fx_origin})")

    statuses: list[SourceStatus] = []
    deals = []

    # ── fase 1: scan (ou descoberta de outputs, se --skip-scan) ─────────
    produced: dict[str, object] = {}
    for src in sources:
        if args.skip_scan:
            continue
        timeout_s = args.timeout or TIMEOUTS[src][args.profile]
        if src == "ct":
            st, det, dur, out = scan_ct(args.profile, stamp, timeout_s)
        elif src == "myp":
            st, det, dur, out = scan_myp(args.profile, stamp, timeout_s)
        elif src == "comc":
            st, det, dur, out = scan_comc(args.profile, stamp, timeout_s)
        else:
            st, det, dur, out = scan_liga(args.profile, stamp, timeout_s)
        produced[src] = out
        statuses.append(SourceStatus(source=src.upper(), status=st, detail=det,
                                     duration_s=dur,
                                     output_path=str(out) if out and not isinstance(out, list)
                                     else "; ".join(str(p) for p in out) if out else ""))

    # ── fase 2: normalizar ───────────────────────────────────────────────
    readers = {
        "ct": (latest_ct_output, read_ct),
        "myp": (latest_myp_output, read_myp),
    }
    for src in sources:
        status_obj = next((s for s in statuses if s.source == src.upper()), None)
        if status_obj is None:
            status_obj = SourceStatus(source=src.upper(), status="pulado (skip-scan)")
            statuses.append(status_obj)
        try:
            src_deals = []
            if src in readers:
                finder, reader = readers[src]
                path = produced.get(src) or finder()
                if path:
                    src_deals = reader(Path(path), fx_global)
                    status_obj.output_path = str(path)
                    if status_obj.status.startswith("pulado"):
                        status_obj.status = "ok (output existente)"
                else:
                    _mark_no_output(status_obj)
            elif src == "comc":
                paths = produced.get(src) or latest_comc_outputs()
                if paths:
                    for p in paths:
                        src_deals += read_comc(Path(p), fx_global)
                    status_obj.output_path = "; ".join(str(p) for p in paths)
                    if status_obj.status.startswith("pulado"):
                        status_obj.status = "ok (output existente)"
                else:
                    # CSV vazio ≠ scan ausente: o sidecar JSON com count==0
                    # prova run bem-sucedido sem deals ("ok (0 deals)").
                    st, det = _comc_phase2_status(comc_run_summaries())
                    if status_obj.status in ("falhou", "timeout"):
                        # scan DESTE run falhou — não mascarar; só anexa.
                        status_obj.detail = (f"{status_obj.detail}; {det}"
                                             if status_obj.detail else det)
                    else:
                        status_obj.status = st
                        status_obj.detail = det
            elif src == "liga":
                path = produced.get(src)
                if not path and args.liga_report:
                    path = Path(args.liga_report)
                if path and Path(path).exists():
                    src_deals = read_liga(Path(path), fx_global)
                    status_obj.output_path = str(path)
                    if not status_obj.detail:        # preserva aviso staleness
                        status_obj.status = "ok"
                elif status_obj.status.startswith("pulado"):
                    status_obj.status = "indisponível"
                    status_obj.detail = (
                        "sem report de CSV real neste run; rode o coletor ao vivo "
                        "no repo da Liga (src/collect_liga_live.py --sets ...) e o "
                        "integrado SEM --skip-scan, ou aponte --liga-report pra um "
                        "report gerado de CSV real (reports MOCK não entram)")
            status_obj.deals_raw = len(src_deals)
            kept = filter_deals(src_deals, args.min_margin, args.notorious_only)
            status_obj.deals_kept = len(kept)
            deals.extend(src_deals)
        except Exception as exc:  # uma fonte quebrada não derruba a entrega
            status_obj.status = "falhou (normalização)"
            status_obj.detail = f"{type(exc).__name__}: {exc}"
            traceback.print_exc(file=sys.stderr)

    # ── fase 3: entrega ─────────────────────────────────────────────────
    final = filter_deals(deals, args.min_margin, args.notorious_only)
    md = build_markdown(final, statuses, fx_global, args.min_margin,
                        args.notorious_only)
    md_path = OUT_DIR / f"integrated_{stamp}.md"
    md_path.write_text(md, encoding="utf-8")
    xlsx_path = OUT_DIR / f"integrated_{stamp}.xlsx"
    write_xlsx(final, xlsx_path)
    print()
    print(md)
    print(f"(apoio local: {md_path} e {xlsx_path} — a entrega oficial é a "
          f"tabela acima, no chat)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
