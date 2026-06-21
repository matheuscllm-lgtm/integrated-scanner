"""API HTTP do scanner integrado — a camada "APIs expostas E alimentadas".

Em português simples: isto liga uma "tomada" HTTP no scanner integrado. Outros
programas (ou você, no navegador) podem PERGUNTAR os deals unificados, o catálogo
de sets, o status de cada fonte — e até DISPARAR um scan coordenado — por URLs,
sem abrir terminal. O scan ALIMENTA o store JSON (api_store.py); a API EXPÕE o
store. Junto com a varredura coordenada por set, fecha a integração completa
entre os 4 scanners.

Subir o servidor:
    cd C:\\Users\\mathe\\integrated-scanner
    .venv\\Scripts\\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8077
Depois abra http://127.0.0.1:8077/docs (Swagger UI interativo, auto-gerado).

Endpoints expostos:
    GET  /                  → info + resumo do último run
    GET  /health            → liveness
    GET  /sets              → catálogo canônico de sets (e como cada fonte cobre)
    GET  /sources           → as 4 fontes + status do último run
    GET  /deals             → deals unificados (filtros: source, set_, min_margin,
                              notorious, q, limit) — LÊ o store alimentado
    GET  /status            → metadados do último run + status por fonte
    POST /scan              → DISPARA um scan coordenado (alimenta o store) em
                              background; devolve job_id
    GET  /scan/{job_id}     → status do job de scan

Princípios preservados: o integrado RANQUEIA/FLAGEIA, NUNCA decide compra; margem
bruta sem taxas; status honesto por fonte. A API só EXPÕE o que o pipeline produz.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

import api_store
from set_registry import (UnknownSetError, catalog, known_canonicals,
                          resolve_scope)

HERE = Path(__file__).resolve().parent
VALID_SOURCES = {"myp", "ct", "comc", "liga"}
# Fontes HEADFUL (abrem Chrome) — NÃO entram no default do /scan via API por
# segurança: rodar headful sem supervisão trava. Opt-in explícito no corpo.
HEADFUL_SOURCES = {"comc", "liga"}

app = FastAPI(
    title="Scanner Integrado de Singles Pokémon — API",
    version="1.0.0",
    description="Camada HTTP sobre a varredura coordenada (MYP+CT+COMC+Liga). "
                "Expõe deals unificados, catálogo de sets e dispara scans.",
)

# Registro de jobs de scan em memória (o processo da API). Reinício = limpa.
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()
_MAX_JOBS = 200  # cap do histórico em memória (evita vazamento em servidor longo)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_store() -> dict:
    store = api_store.load_store()
    if store is None:
        raise HTTPException(
            status_code=404,
            detail="Nenhum scan rodou ainda (store vazio). Dispare POST /scan "
                   "ou rode run_integrated.py, e tente de novo.")
    return store


# ── leitura: catálogo, fontes, deals, status ────────────────────────────────
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "time": _now()}


@app.get("/")
def root() -> dict:
    store = api_store.load_store()
    last = None
    if store:
        last = {"generated_utc": store.get("generated_utc"),
                "scope": store.get("scope"),
                "deal_count": store.get("deal_count"),
                "fx": store.get("fx")}
    return {
        "service": "integrated-scanner-api",
        "version": app.version,
        "endpoints": ["/health", "/sets", "/sources", "/deals", "/status",
                      "/scan (POST)", "/scan/{job_id}", "/docs"],
        "last_run": last,
    }


@app.get("/sets")
def sets() -> dict:
    """Catálogo canônico de sets + como cada fonte cobre cada um."""
    return {"count": len(known_canonicals()), "sets": catalog()}


@app.get("/sources")
def sources() -> dict:
    """As 4 fontes + o status do último run (do store, se houver)."""
    store = api_store.load_store()
    by_src = {s["source"].lower(): s for s in (store or {}).get("sources", [])}
    out = []
    for src in sorted(VALID_SOURCES):
        st = by_src.get(src)
        out.append({
            "source": src,
            "headful": src in HEADFUL_SOURCES,
            "last_status": st["status"] if st else "sem run",
            "last_detail": st.get("detail", "") if st else "",
            "deals_kept": st.get("deals_kept", 0) if st else 0,
        })
    return {"sources": out, "last_run": (store or {}).get("generated_utc")}


@app.get("/status")
def status() -> dict:
    """Metadados do último run + status honesto por fonte."""
    store = _require_store()
    return {
        "generated_utc": store.get("generated_utc"),
        "stamp": store.get("stamp"),
        "scope": store.get("scope"),
        "fx": store.get("fx"),
        "min_margin_pct": store.get("min_margin_pct"),
        "deal_count": store.get("deal_count"),
        "sources": store.get("sources", []),
    }


@app.get("/deals")
def deals(
    source: Optional[str] = Query(None, description="filtra por fonte (myp/ct/comc/liga)"),
    set_: Optional[str] = Query(None, alias="set", description="filtra por set canônico (PRE) ou nome"),
    min_margin: Optional[float] = Query(None, description="margem bruta mínima (percent)"),
    notorious: bool = Query(False, description="só Pokémon notórios (⭐)"),
    q: Optional[str] = Query(None, description="busca por substring no nome da carta"),
    limit: int = Query(200, ge=1, le=2000, description="máximo de linhas"),
) -> dict:
    """Deals unificados do último run (store alimentado), com filtros. Ordenado
    por margem bruta desc. NÃO recomenda compra — só ranqueia e flagea."""
    store = _require_store()
    rows = list(store.get("deals", []))

    if source:
        src = source.strip().lower()
        if src not in VALID_SOURCES:
            raise HTTPException(400, f"source inválida: {source} (válidas: {sorted(VALID_SOURCES)})")
        rows = [d for d in rows if (d.get("fonte") or "").lower() == src]
    if set_:
        # set_ pode ser um código canônico (PRE) ou um pedaço do nome. Se for
        # canônico conhecido, casamos pelo NOME do set (os deals guardam o nome
        # completo, ex. "Prismatic Evolutions"); senão, substring direta.
        raw = set_.strip()
        canon = {e["canonical"]: e["name"] for e in catalog()}
        key = canon.get(raw.upper(), raw).lower()
        rows = [d for d in rows if key in (d.get("set_name") or "").lower()]
    if min_margin is not None:
        rows = [d for d in rows if float(d.get("margem_pct") or 0) >= min_margin]
    if notorious:
        rows = [d for d in rows if (d.get("notorio") or "").strip()]
    if q:
        needle = q.strip().lower()
        rows = [d for d in rows if needle in (d.get("carta") or "").lower()]

    rows.sort(key=lambda d: float(d.get("margem_pct") or 0), reverse=True)
    return {
        "count": len(rows),
        "generated_utc": store.get("generated_utc"),
        "scope": store.get("scope"),
        "fx": store.get("fx"),
        "deals": rows[:limit],
    }


# ── escrita: disparar um scan coordenado (alimenta o store) ──────────────────
class ScanRequest(BaseModel):
    sets: str = Field("quick", description="escopo: códigos canônicos (PRE,SSP) ou profile (quick/full)")
    sources: list[str] = Field(default_factory=lambda: ["myp", "ct"],
                               description="fontes a rodar (headful comc/liga exigem opt-in)")
    min_margin: float = Field(30.0, description="corte de margem bruta (percent)")
    collect_liga: bool = Field(False, description="dispara coleta Liga headful (cuidado)")
    allow_comc: bool = Field(False, description="permite COMC (HEADFUL — abre Chrome); opt-in obrigatório")
    notorious_only: bool = Field(False)


def _prune_jobs(keep: int = _MAX_JOBS) -> None:
    """Cap simples no histórico de jobs em memória (evita vazamento). Mantém os
    `keep` mais recentes por ordem de criação; preserva jobs ainda ativos."""
    with _JOBS_LOCK:
        if len(_JOBS) <= keep:
            return
        items = list(_JOBS.items())  # ordem de inserção (criação)
        for jid, j in items[:-keep]:
            if j.get("status") not in ("queued", "running"):
                _JOBS.pop(jid, None)


def _run_scan_job(job_id: str, req: ScanRequest) -> None:
    cmd = [sys.executable, str(HERE / "run_integrated.py"),
           "--sets", req.sets,
           "--sources", ",".join(s.lower() for s in req.sources),
           "--min-margin", str(req.min_margin)]
    if req.collect_liga:
        cmd.append("--collect-liga")
    if req.notorious_only:
        cmd.append("--notorious-only")
    log_path = api_store.OUT_DIR / f"api_scan_{job_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with _JOBS_LOCK:
        _JOBS[job_id].update(status="running", cmd=" ".join(cmd))
    try:
        with log_path.open("w", encoding="utf-8", errors="replace") as log:
            proc = subprocess.run(cmd, cwd=str(HERE), stdout=log,
                                  stderr=subprocess.STDOUT)
        with _JOBS_LOCK:
            _JOBS[job_id].update(
                status="done" if proc.returncode == 0 else "failed",
                returncode=proc.returncode, finished=_now(),
                log=str(log_path))
    except Exception as exc:  # pragma: no cover
        with _JOBS_LOCK:
            _JOBS[job_id].update(status="failed", error=f"{type(exc).__name__}: {exc}",
                                 finished=_now(), log=str(log_path))


@app.post("/scan", status_code=202)
def scan(req: ScanRequest) -> dict:
    """Dispara um scan coordenado em BACKGROUND (alimenta o store). Valida o
    escopo e as fontes antes. COMC (headful) exige `allow_comc=true`; coleta
    Liga ao vivo exige `collect_liga=true`. Rejeita 409 se já houver scan ativo
    (nunca 2 runs concorrentes — corromperia o store / colidiria no state-dir)."""
    srcs = [s.lower() for s in req.sources]
    bad = [s for s in srcs if s not in VALID_SOURCES]
    if bad:
        raise HTTPException(400, f"fontes inválidas: {bad} (válidas: {sorted(VALID_SOURCES)})")
    # COMC é SEMPRE headful (abre Chrome) → opt-in obrigatório (allow_comc).
    if "comc" in srcs and not req.allow_comc:
        raise HTTPException(
            400, "COMC é headful (abre Chrome) — passe allow_comc=true pra confirmar "
                 "(rodar headful sem supervisão pode travar).")
    try:  # valida o escopo cedo (erro claro em vez de subprocess que falha)
        resolve_scope(req.sets)
    except UnknownSetError as exc:
        raise HTTPException(400, str(exc))
    # GUARD de concorrência (ATÔMICO, sob 1 lock pra não ter TOCTOU): 2 scans
    # juntos = 2 run_integrated no mesmo OUT_DIR (corrompe o store) + colidem no
    # state-dir de cada scanner-fonte (regra do operador: nunca 2 no mesmo
    # state-dir). Rejeita 409 enquanto houver job ativo; cria o job na mesma
    # seção crítica antes de soltar a thread.
    job_id = uuid.uuid4().hex[:12]
    with _JOBS_LOCK:
        active = next((jid for jid, j in _JOBS.items()
                       if j.get("status") in ("queued", "running")), None)
        if active:
            raise HTTPException(
                409, f"já há um scan em andamento (job {active}); aguarde concluir "
                     f"(GET /scan/{active}) antes de disparar outro.")
        _JOBS[job_id] = {"job_id": job_id, "status": "queued", "created": _now(),
                         "sets": req.sets, "sources": req.sources}
    _prune_jobs()
    threading.Thread(target=_run_scan_job, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id, "status": "queued",
            "note": "scan rodando em background; consulte GET /scan/{job_id}. "
                    "Quando 'done', os novos deals aparecem em GET /deals."}


@app.get("/scan/{job_id}")
def scan_status(job_id: str) -> dict:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, f"job desconhecido: {job_id}")
    return job
