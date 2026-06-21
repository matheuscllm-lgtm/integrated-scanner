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
import csv
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
from delivery import (MIN_MARGIN_PCT_DEFAULT, SourceStatus,
                      build_cross_source_markdown, build_markdown,
                      filter_deals, write_xlsx)
from cross_source import group_cross_source
from set_registry import (UnknownSetError, is_full, resolve_scope, to_comc,
                          to_ct_sets, to_liga_codes, to_liga_names,
                          to_myp_editions)

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "outputs"
LOG_DIR = OUT_DIR / "logs"

VENV_PY = {  # python.exe do venv de CADA repo (caixa-preta: usamos o deles)
    "ct": REPOS["ct"] / ".venv" / "Scripts" / "python.exe",
    "myp": REPOS["myp"] / ".venv" / "Scripts" / "python.exe",
    "comc": REPOS["comc"] / ".venv" / "Scripts" / "python.exe",
    "liga": REPOS["liga"] / ".venv" / "Scripts" / "python.exe",
}

# A varredura coordenada por set vive em set_registry.py: um código canônico
# (PRE, SSP, ...) traduzido pra convenção de cada fonte. O escopo é resolvido UMA
# vez em main() (profile "quick"/"full" OU lista livre --sets PRE,SSP) e passado
# pra cada scan_*. As listas quick antigas (CT_QUICK_SETS / MYP_QUICK_EDITIONS)
# viraram o profile "quick" do registry — reprodução byte-a-byte travada em testes.

# Timeouts (segundos) por fonte × profile — generosos mas finitos.
TIMEOUTS = {
    "ct":   {"quick": 45 * 60, "full": 4 * 3600},
    "myp":  {"quick": 2 * 3600, "full": 8 * 3600},   # ~7 min/edição no MYP
    "comc": {"quick": 30 * 60, "full": 75 * 60},     # ~8 min/era + margem
    "liga": {"quick": 15 * 60, "full": 30 * 60},
}

# Timeout próprio da COLETA ao vivo da Liga (modo --collect-liga, headful). É um
# passo à parte: se estourar, a Liga vira "timeout (coleta)" mas o run continua
# com as outras fontes (isolamento — uma fonte frágil não derruba a entrega).
LIGA_COLLECT_TIMEOUT = 90 * 60


def _skip_note(skipped: list[str], reason: str) -> str:
    """Nota honesta p/ o status quando parte do escopo não é coberta pela fonte."""
    return f"sets fora do escopo desta fonte ({reason}): {', '.join(skipped)}" if skipped else ""

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


def _liga_csv_set_names(csv_path: Path) -> set[str]:
    """Nomes de set presentes no liga_offers.csv (coluna set_name). O CSV guarda
    o nome COMPLETO ('Prismatic Evolutions'), não o código — por isso a cobertura
    é checada por nome (que o registry conhece exatamente)."""
    try:
        with csv_path.open(encoding="utf-8", newline="") as fh:
            return {(r.get("set_name") or "").strip()
                    for r in csv.DictReader(fh) if (r.get("set_name") or "").strip()}
    except (OSError, csv.Error):
        return set()


def _liga_coverage_note(csv_path: Path, wanted_names: list[str]) -> str:
    """Aviso se o CSV da Liga NÃO cobre parte do escopo pedido (modo sem coleta).
    Honesto: não finge cobertura. None/'' se cobre tudo (ou nada foi pedido)."""
    if not wanted_names:
        return ""
    have = _liga_csv_set_names(csv_path)
    missing = [n for n in wanted_names if n not in have]
    if not missing:
        return ""
    return (f"⚠️ CSV da Liga não cobre {', '.join(missing)} — rode a coleta ao "
            f"vivo desses sets (--collect-liga ou collect_liga_live.py) p/ a Liga "
            f"entrar no escopo")


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


def scan_ct(scope: object, stamp: str, timeout_s: int) -> tuple[str, str, float, Path | None]:
    repo = REPOS["ct"]
    out = repo / "outputs" / f"integrated_{stamp}.xlsx"
    cmd = [str(VENV_PY["ct"]), str(repo / "cardtrader_scanner.py")]
    note = ""
    if is_full(scope):
        cmd += ["--all-sets"]
    else:
        ct_sets, skipped = to_ct_sets(scope)
        if not ct_sets:  # escopo só tem sets que o CT não cobre (ex.: só ME)
            return ("pulado (escopo)",
                    _skip_note(skipped, "CT não cobre — ex.: era ME sem preço TCG real"),
                    0.0, None)
        cmd += ["--sets", *ct_sets]
        note = _skip_note(skipped, "CT não cobre")
    # THRESHOLD EM FRAÇÃO (0.30 = 30%) — convenção do CT, não mudar!
    cmd += ["--threshold", "0.30", "--chase-only", "--validate-top", "30",
            "--max-consecutive-misses", "40", "--output", str(out)]
    status, detail, dur = _run_step("ct", cmd, repo, timeout_s,
                                    LOG_DIR / f"ct_{stamp}.log")
    if note:
        detail = f"{detail}; {note}" if detail else note
    if status == "ok" and out.exists():
        # postprocess do CT (best-effort): gera o .md/.xlsx no formato CT.
        post = repo / "outputs" / f"integrated_{stamp}_post.xlsx"
        _run_step("ct-post", [str(VENV_PY["ct"]), str(repo / "cardtrader_postprocess.py"),
                              "--input", str(out), "--output", str(post)],
                  repo, 600, LOG_DIR / f"ct_post_{stamp}.log")
        return status, detail, dur, out
    return status, detail, dur, (out if out.exists() else None)


def scan_myp(scope: object, stamp: str, timeout_s: int) -> tuple[str, str, float, Path | None]:
    repo = REPOS["myp"]
    out = repo / "results" / f"integrated_{stamp}.xlsx"
    cmd = [str(VENV_PY["myp"]), str(repo / "myp_arbitrage_scanner.py"),
           # THRESHOLD EM PERCENT INTEIRO (30 = 30%) — convenção do MYP!
           "--threshold", "30", "--min-price", "50", "-o", str(out)]
    note = ""
    if not is_full(scope):  # full = sem --editions (varre catálogo inteiro)
        myp_eds, skipped = to_myp_editions(scope)
        if not myp_eds:
            return ("pulado (escopo)", _skip_note(skipped, "MYP não cobre"), 0.0, None)
        cmd += ["--editions", *myp_eds]
        note = _skip_note(skipped, "MYP não cobre")
    status, detail, dur = _run_step("myp", cmd, repo, timeout_s,
                                    LOG_DIR / f"myp_{stamp}.log")
    if note:
        detail = f"{detail}; {note}" if detail else note
    return status, detail, dur, (out if out.exists() else None)


def scan_comc(scope: object, stamp: str, timeout_s: int) -> tuple[str, str, float, list[Path]]:
    repo = REPOS["comc"]
    # O COMC scaneia por ERA mas aceita allowlist --sets DENTRO da era. Em modo
    # escopo, varremos só as eras necessárias filtrando pelos abbrevs pedidos
    # (mais coerente E mais rápido que varrer a era inteira). Em full, recent+
    # vintage sem allowlist (comportamento histórico).
    skipped: list[str] = []
    if is_full(scope):
        era_groups: list[tuple[str, list[str] | None]] = [("recent", None), ("vintage", None)]
    else:
        groups, skipped = to_comc(scope)
        if not groups:  # escopo só tem sets que o COMC não cobre (ex.: só ME)
            return ("pulado (escopo)",
                    _skip_note(skipped, "COMC não cobre — ex.: era ME sem slug"),
                    0.0, [])
        era_groups = [(era, abbrevs) for era, abbrevs in groups]
    print("[comc] ATENÇÃO: o COMC é HEADFUL — vai abrir uma janela do Chrome "
          "de verdade (necessário pro Cloudflare). Não feche a janela.")
    t_start = time.time()  # p/ não confundir CSV deste run com sobra de run antigo
    overall, details, total_dur = "ok", [], 0.0
    for era, abbrevs in era_groups:
        cmd = [str(VENV_PY["comc"]), "-m", "comc_scanner", "targeted",
               "--era", era, "--fetch-mode", "playwright", "--no-sheets",
               "--restart", "--chase-only"]
        if abbrevs:  # allowlist do COMC: nomes/abbrevs separados por vírgula
            cmd += ["--sets", ",".join(abbrevs)]
        # margem default do COMC já é 0.30 (FRAÇÃO) + piso $10 — canônicos.
        status, detail, dur = _run_step(f"comc-{era}", cmd, repo, timeout_s,
                                        LOG_DIR / f"comc_{era}_{stamp}.log")
        total_dur += dur
        if status != "ok":
            overall = status
            details.append(f"{era}: {detail}")
    note = _skip_note(skipped, "COMC não cobre")
    if note:
        details.append(note)
    # IMPORTANTE: o COMC mantém um *_latest.csv FIXO por era (sobrescrito). Só
    # devolvemos os das eras VARRIDAS neste run E escritos AGORA (mtime>=t_start)
    # — senão um vintage_latest.csv de um run --full anterior vazaria deals fora
    # do escopo (ex.: WotC vintage numa run --sets PRE,SSP que só varreu recent).
    scanned_eras = {era for era, _ in era_groups}
    outs = [p for p in latest_comc_outputs(repo)
            if any(f"comc_deals_{e}_latest" in p.name for e in scanned_eras)
            and p.stat().st_mtime >= t_start]
    return overall, "; ".join(details), total_dur, outs


def collect_liga(scope: object, stamp: str) -> tuple[str, str]:
    """Dispara a COLETA ao vivo da Liga pros sets do escopo (HEADFUL — abre
    Chrome). Passo à parte, com timeout próprio: se falhar/estourar, devolve o
    status mas o run da Liga continua tentando ler o CSV que houver. NÃO roda em
    full (coletar o catálogo inteiro ao vivo é inviável)."""
    repo = REPOS["liga"]
    if is_full(scope):
        return "pulado (coleta)", "--collect-liga não se aplica a full (coleta ao vivo do catálogo inteiro é inviável)"
    liga_codes, _ = to_liga_codes(scope)
    if not liga_codes:
        return "pulado (coleta)", "nenhum set do escopo existe na Liga (ex.: era ME)"
    cmd = [str(VENV_PY["liga"]), str(repo / "src" / "collect_liga_live.py"),
           "--sets", *liga_codes, "--no-report"]
    print("[liga-collect] ATENÇÃO: coleta ao vivo HEADFUL — abre janela do Chrome "
          "(patchright fura o Cloudflare). Não feche a janela.")
    status, detail, _dur = _run_step("liga-collect", cmd, repo, LIGA_COLLECT_TIMEOUT,
                                     LOG_DIR / f"liga_collect_{stamp}.log")
    if status == "timeout":
        return "timeout (coleta)", f"coleta da Liga excedeu {LIGA_COLLECT_TIMEOUT//60} min"
    if status != "ok":
        return f"{status} (coleta)", detail
    return "ok (coleta)", f"coletou {', '.join(liga_codes)}"


def scan_liga(scope: object, stamp: str, timeout_s: int,
              collect: bool = False) -> tuple[str, str, float, Path | None]:
    """Liga roda a partir do data/liga_offers.csv do repo da Liga.

    Dois modos:
      - collect=False (padrão): consome o CSV mais recente (gerado pelo coletor
        ao vivo de lá, headful) e AVISA se ele não cobre os sets do escopo. Não
        dispara coleta — ela é headful/lenta e não roda sozinha de madrugada.
      - collect=True (--collect-liga): dispara a coleta ao vivo dos sets do
        escopo ANTES de ler (passo headful com timeout próprio; se falhar, segue
        lendo o CSV que houver). É opt-in justamente por ser headful."""
    repo = REPOS["liga"]
    collect_note = ""
    if collect:
        cstatus, cdetail = collect_liga(scope, stamp)
        collect_note = f"coleta: {cstatus} ({cdetail})" if cdetail else f"coleta: {cstatus}"
    csv_real = repo / "data" / "liga_offers.csv"
    if not csv_real.exists():
        base = ("sem data/liga_offers.csv; rode o coletor ao vivo no repo da Liga "
                "(src/collect_liga_live.py --sets ... --no-report) ou use "
                "--collect-liga, e re-rode")
        return ("indisponível", f"{base}; {collect_note}" if collect_note else base, 0.0, None)
    stale = _staleness_warning(csv_real.stat().st_mtime)
    wanted = [] if is_full(scope) else to_liga_names(scope)
    coverage = "" if collect else _liga_coverage_note(csv_real, wanted)
    cmd = [str(VENV_PY["liga"]), str(repo / "src" / "main.py")]
    status, detail, dur = _run_step(
        "liga", cmd, repo, timeout_s, LOG_DIR / f"liga_{stamp}.log",
        env_extra={"LIGA_OFFERS_SOURCE": "csv", "LIGA_TCG_SOURCE": "pokemontcg"})
    for extra in (collect_note, coverage, stale):  # avisos — nunca bloqueiam o run
        if extra:
            detail = f"{extra}; {detail}" if detail else extra
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
    ap.add_argument("--profile", choices=["quick", "full"], default=None,
                    help="quick = principais sets SV+ME; full = catálogo inteiro "
                         "(HORAS). Default quick. Mutuamente exclusivo com --sets.")
    ap.add_argument("--sets", type=str, default=None,
                    help="ESCOPO COORDENADO: códigos canônicos de set separados "
                         "por vírgula (ex.: PRE,SSP,SCR) — os 4 scanners varrem "
                         "EXATAMENTE esses sets, cada um na sua convenção. Também "
                         "aceita um profile (quick/full). Mutuamente exclusivo com "
                         "--profile.")
    ap.add_argument("--collect-liga", action="store_true",
                    help="dispara a COLETA ao vivo da Liga (HEADFUL, abre Chrome) "
                         "pros sets do escopo ANTES de ler. Opt-in: sem isto, a "
                         "Liga só consome o CSV existente e avisa se não cobre o "
                         "escopo. NÃO use sozinho de madrugada sem supervisão.")
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

    # ── ESCOPO COORDENADO: --sets e --profile são mutuamente exclusivos ──────
    if args.sets and args.profile:
        ap.error("--sets e --profile são mutuamente exclusivos (escolha um)")
    scope_spec = args.sets or args.profile or "quick"  # default histórico
    try:
        scope = resolve_scope(scope_spec)
    except UnknownSetError as exc:
        ap.error(str(exc))
    # quick/full mapeiam pros timeouts existentes; escopo livre usa o de "quick"
    timeout_profile = "full" if is_full(scope) else "quick"
    scope_label = ("full (catálogo inteiro)" if is_full(scope)
                   else ", ".join(e.canonical for e in scope))
    print(f"Escopo de sets: {scope_label}")
    if args.collect_liga and "liga" in sources and not is_full(scope) \
            and not args.skip_scan:
        print("[liga] --collect-liga ATIVO: a coleta ao vivo (headful) será "
              "disparada pros sets do escopo.")
    if args.skip_scan and args.sets:
        # Honesto: --skip-scan re-lê o output MAIS RECENTE de cada fonte, que pode
        # ter sido gerado com OUTRO escopo. Não filtramos as linhas pelo escopo
        # aqui (as fontes não expõem código de set por linha uniformemente).
        print("[aviso] --sets é IGNORADO em --skip-scan: a tabela reflete os "
              "outputs mais recentes de cada fonte, no escopo em que foram "
              "gerados (não há filtro por set na releitura).")
    if args.skip_scan and args.collect_liga:
        print("[aviso] --collect-liga é IGNORADO em --skip-scan (a fase de scan "
              "não roda; nenhuma coleta é disparada).")
    # Escopo livre grande herda o timeout de "quick" — avisa pra usar --timeout.
    if not is_full(scope) and not args.skip_scan and not args.timeout \
            and len(scope) > len(resolve_scope("quick")):
        print(f"[aviso] escopo com {len(scope)} sets usa o timeout de 'quick' por "
              f"fonte (MYP {TIMEOUTS['myp']['quick']//60} min etc.); escopos "
              f"grandes podem estourar — considere --timeout <segundos>.")

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
        timeout_s = args.timeout or TIMEOUTS[src][timeout_profile]
        try:
            if src == "ct":
                st, det, dur, out = scan_ct(scope, stamp, timeout_s)
            elif src == "myp":
                st, det, dur, out = scan_myp(scope, stamp, timeout_s)
            elif src == "comc":
                st, det, dur, out = scan_comc(scope, stamp, timeout_s)
            else:
                st, det, dur, out = scan_liga(scope, stamp, timeout_s,
                                              collect=args.collect_liga)
        except Exception as exc:  # isolamento: 1 fonte quebrada não derruba o run
            st, det, dur, out = "falhou", f"{type(exc).__name__}: {exc}", None, None
            traceback.print_exc(file=sys.stderr)
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
        # Fonte fora do escopo desta run NÃO lê output antigo (senão a tabela
        # mostraria deals stale de um scan anterior, fora do escopo pedido).
        if status_obj.status.startswith("pulado (escopo)"):
            continue
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
    # Seção ADITIVA: a mesma carta em ≥2 fontes, preço lado a lado (não substitui
    # a tabela plana acima — regra do operador é mostrar TODOS os deals).
    cross = group_cross_source(final)
    md += "\n" + build_cross_source_markdown(cross, args.min_margin)
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
