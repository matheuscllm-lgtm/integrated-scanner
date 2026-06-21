"""Store unificado de deals — a camada "alimentada" da integração via API.

Em português simples: depois que o scan integrado roda, ele GRAVA aqui um único
arquivo JSON (`outputs/deals_store.json`) com TODOS os deals unificados + o
status de cada fonte + metadados do run (escopo, câmbio, quando rodou). A API
HTTP (`api.py`) LÊ esse arquivo e serve os dados — é o "APIs expostas E
alimentadas": o pipeline ALIMENTA o store, a API EXPÕE o store.

Por que um arquivo JSON (e não um banco): o integrado já é stateless e roda sob
demanda; o store é o snapshot do último run, reproduzível re-rodando o scan.
Zero dependência nova, atômico (grava em tmp + rename), e o histórico fica em
`outputs/deals_store_<stamp>.json` pra auditoria.

Tudo aqui é puro (sem rede). Não toca em threshold/FX/repos-fonte.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "outputs"
STORE_PATH = OUT_DIR / "deals_store.json"

SCHEMA_VERSION = 1


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_store(deals: list, statuses: list, *, scope: Any, fx: float,
                min_margin: float, stamp: str,
                notorious_only: bool = False) -> dict:
    """Monta o dict do store a partir dos objetos do pipeline (Deal/SourceStatus
    são dataclasses → asdict serializa tudo, inclusive a lista de notas)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": _now_utc_iso(),
        "stamp": stamp,
        "scope": scope,                  # lista de códigos canônicos OU "full"
        "fx": round(float(fx), 4),
        "min_margin_pct": float(min_margin),
        "notorious_only": bool(notorious_only),
        "deal_count": len(deals),
        "sources": [asdict(s) for s in statuses],
        "deals": [asdict(d) for d in deals],
    }


def save_store(store: dict, path: Path = STORE_PATH,
               keep_history: bool = True) -> Path:
    """Grava o store de forma ATÔMICA (tmp + rename) + cópia histórica datada.
    Falha de gravação NUNCA deve derrubar o run — chame em try/except no caller."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(store, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)  # atômico no mesmo filesystem
    if keep_history and store.get("stamp"):
        hist = path.parent / f"deals_store_{store['stamp']}.json"
        hist.write_text(payload, encoding="utf-8")
    return path


def load_store(path: Path = STORE_PATH) -> Optional[dict]:
    """Lê o store mais recente; None se ainda não existe (nenhum scan rodou)."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
