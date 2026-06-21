"""Testes da camada API (FastAPI) + store alimentado.

Cobre: endpoints de leitura (health/sets/sources/deals/status com filtros),
o contrato do store (build/save/load round-trip), e a VALIDAÇÃO do POST /scan
(escopo/fontes inválidos → 400) SEM disparar scan real (subprocess mockado).
"""
import importlib

import pytest
from fastapi.testclient import TestClient

import api
import api_store
from delivery import SourceStatus
from normalize import Deal


@pytest.fixture
def client():
    return TestClient(api.app)


def _sample_store() -> dict:
    deals = [
        Deal(fonte="MYP", carta="Sinistcha ex", set_name="SV06: Twilight Masquerade",
             numero="210", raridade="Rara", margem_pct=95.2, compra_brl=89.0,
             ref_brl=173.7, notas=["1 sellers NM"]),
        Deal(fonte="MYP", carta="Salamence ex", set_name="SV09: Journey Together",
             numero="187", margem_pct=31.9, compra_brl=279.8, ref_brl=368.96,
             notorio="⭐ Salamence"),
        Deal(fonte="CT", carta="Dusclops", set_name="sfa", numero="069",
             margem_pct=40.0, compra_usd=10.0, ref_usd=14.0),
    ]
    statuses = [
        SourceStatus(source="MYP", status="ok", deals_raw=2, deals_kept=2),
        SourceStatus(source="CT", status="ok", deals_raw=1, deals_kept=1,
                     detail="sets fora do escopo desta fonte (CT não cobre): ASH"),
    ]
    return api_store.build_store(deals, statuses, scope=["TWM", "JTG", "SFA"],
                                 fx=5.20, min_margin=30.0, stamp="TEST_STAMP")


@pytest.fixture
def seeded(monkeypatch):
    store = _sample_store()
    monkeypatch.setattr(api_store, "load_store", lambda *a, **k: store)
    return store


# ── store round-trip ─────────────────────────────────────────────────────────
def test_store_build_roundtrip(tmp_path):
    store = _sample_store()
    p = tmp_path / "store.json"
    api_store.save_store(store, path=p, keep_history=False)
    loaded = api_store.load_store(p)
    assert loaded["deal_count"] == 3
    assert loaded["scope"] == ["TWM", "JTG", "SFA"]
    assert loaded["deals"][0]["carta"] == "Sinistcha ex"
    assert loaded["sources"][1]["source"] == "CT"


# ── leitura ──────────────────────────────────────────────────────────────────
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_sets_catalog(client):
    r = client.get("/sets")
    assert r.status_code == 200
    body = r.json()
    canon = {s["canonical"]: s for s in body["sets"]}
    assert canon["PRE"]["sources"]["ct"] == "pre"
    assert canon["PRE"]["sources"]["myp"] == "Prismatic"
    # ME só no MYP
    assert canon["ASH"]["sources"]["liga"] is None
    assert canon["ASH"]["sources"]["comc"] is None
    assert canon["ASH"]["covered_by"] == ["myp"]


def test_deals_no_store_404(client, monkeypatch):
    monkeypatch.setattr(api_store, "load_store", lambda *a, **k: None)
    assert client.get("/deals").status_code == 404


def test_deals_all(client, seeded):
    r = client.get("/deals")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    # ordenado por margem desc
    margins = [d["margem_pct"] for d in body["deals"]]
    assert margins == sorted(margins, reverse=True)


def test_deals_filter_source(client, seeded):
    r = client.get("/deals", params={"source": "ct"})
    assert r.json()["count"] == 1 and r.json()["deals"][0]["fonte"] == "CT"


def test_deals_filter_min_margin(client, seeded):
    r = client.get("/deals", params={"min_margin": 50})
    assert r.json()["count"] == 1  # só Sinistcha 95.2


def test_deals_filter_notorious(client, seeded):
    r = client.get("/deals", params={"notorious": True})
    assert r.json()["count"] == 1 and "Salamence" in r.json()["deals"][0]["carta"]


def test_deals_filter_set_canonical(client, seeded):
    # filtrar por código canônico TWM → casa o nome "...Twilight Masquerade"
    r = client.get("/deals", params={"set": "TWM"})
    assert r.json()["count"] == 1 and "Twilight" in r.json()["deals"][0]["set_name"]


def test_deals_search_q(client, seeded):
    r = client.get("/deals", params={"q": "salamence"})
    assert r.json()["count"] == 1


def test_deals_bad_source_400(client, seeded):
    assert client.get("/deals", params={"source": "ebay"}).status_code == 400


def test_sources_lists_four(client, seeded):
    r = client.get("/sources")
    srcs = {s["source"] for s in r.json()["sources"]}
    assert srcs == {"myp", "ct", "comc", "liga"}
    comc = next(s for s in r.json()["sources"] if s["source"] == "comc")
    assert comc["headful"] is True


def test_status(client, seeded):
    r = client.get("/status")
    assert r.status_code == 200
    assert r.json()["deal_count"] == 3
    assert r.json()["scope"] == ["TWM", "JTG", "SFA"]


# ── escrita (POST /scan) — sem disparar scan real ────────────────────────────
def test_scan_bad_source_400(client):
    r = client.post("/scan", json={"sets": "PRE", "sources": ["ebay"]})
    assert r.status_code == 400


def test_scan_bad_set_400(client):
    r = client.post("/scan", json={"sets": "ZZZ", "sources": ["myp"]})
    assert r.status_code == 400


def test_scan_valid_returns_job(client, monkeypatch):
    # não rodar scan real: troca o worker por no-op
    monkeypatch.setattr(api, "_run_scan_job", lambda *a, **k: None)
    monkeypatch.setattr(api.threading, "Thread",
                        lambda *a, **k: type("T", (), {"start": lambda self: None})())
    r = client.post("/scan", json={"sets": "PRE,SSP", "sources": ["myp", "ct"]})
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    assert client.get(f"/scan/{job_id}").status_code == 200


def test_scan_status_unknown_404(client):
    assert client.get("/scan/deadbeef").status_code == 404
