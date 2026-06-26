# HANDOFF 02 — sessão nuvem (scan integrado 10→20 sets)

> Gerado por uma sessão Claude Code **na nuvem** em **2026-06-24**. Continua o
> `HANDOFF.md` (2026-06-20). Ponto de partida pra retomar (nuvem ou PC do Matheus).
> ⚠️ **Sem segredos** (repos públicos) — `CT_JWT`/`POKEMONTCG_API_KEY` não estão aqui.

---

## 0. TL;DR — o que esta sessão fez
1. Rodou o **scanner integrado (MYP + CardTrader)** na nuvem p/ os últimos 10 e
   depois 16 sets (MYP+CT só; COMC/Liga não rodam na nuvem — ver §5).
2. Achou e **consertou 1 bug real** (MYP perdia o scan inteiro no save).
3. **Removeu a coluna Valorização** do formato de entrega do integrado.
4. **Fechou o registro em 20 sets** (+4 SWSH).
- **3 PRs já MERGEADOS no `main`.** ➡️ **Próximo passo:** rodar o scan dos **20 sets
  no PC** (§4) — na nuvem está bloqueado agora (§3).

## 1. PRs mergeados (todos no `main`)
| PR | Repo | O quê |
|---|---|---|
| **#68** | myp-arbitrage-scanner | `fix`: `generate_xlsx` cria `results/` se ausente. Num clone limpo a pasta não vinha → `wb.save` quebrava com `FileNotFoundError` **depois** de ~90 min de scan, perdendo tudo. +teste de regressão (54 verdes). |
| **#14** | integrated-scanner | `remove`: coluna **Valorização (0-100)** do formato de entrega (não era padrão cross-scanner). Tirada de `UNIFIED_COLUMNS` (markdown+xlsx) + `to_row()` + nota de rodapé + docs. O motor `compute_valorization()` **fica interno** (leitura nativa do CT). 86 testes verdes. |
| **#19** | integrated-scanner | `feat`: +4 sets SWSH no registro → **20 sets**. |

## 2. Registro de sets agora = 20 (`set_registry.py`)
13 SV + **4 SWSH novos** + 3 ME. Os novos:

| Canon | Nome | CT (✓API) | Liga | COMC | MYP |
|---|---|---|---|---|---|
| LOR | Lost Origin | `lorg` | `LOR` | None | "Lost Origin" |
| SIT | Silver Tempest | `sit` | `STB` | None | "Silver Tempest" |
| CRZ | Crown Zenith | `crz` | None | None | "Crown Zenith" |
| ASR | Astral Radiance | `astr` | None | None | "Astral Radiance" |

- **CT** = verificado via `/expansions` API (autoritativo).
- **Liga** = LOR/STB constam no alias map; CRZ/ASR ausentes → `None`.
- **COMC** = sem slug em `comc_set_slugs.json` → `None` (não cobre, igual ME).
- **MYP** = nome canônico EN. ⚠️ **NÃO live-verificado** (mypcards 403 hoje, §3) —
  confirmar no próximo run sem bloqueio. Erro de substring = **no-op** (casa 0
  edições), nunca escaneia set errado → seguro.
- **SV base (Scarlet & Violet) ficou de fora DE PROPÓSITO:** a substring
  "Scarlet & Violet" casaria **todos** os sets SV (corrupção). Os 4 SWSH têm
  subtítulo único, sem esse risco.

## 3. ⚠️ Bloqueio ativo: mypcards 403 neste IP
Depois do scan pesado de hoje, a Cloudflare do **mypcards.com** passou a devolver
**HTTP 403** pra este IP de datacenter (home volta 5594 bytes = challenge). Por isso:
- **não deu** pra re-rodar o scan dos 20 sets na nuvem (MYP falharia na largada);
- **não deu** pra live-verificar as substrings MYP dos 4 sets novos.
Resolve sozinho em ~horas, **ou** rode no PC (IP residencial, sem bloqueio).

## 4. Rodar o scan dos 20 sets — no PC (recomendado: 4 fontes)
```powershell
cd C:\Users\mathe\integrated-scanner
git pull origin main          # pega os 3 fixes (#68, #14, #19)
.venv\Scripts\python.exe run_integrated.py `
  --sets PRE,SSP,JTG,SCR,TWM,SFA,PAF,MEW,DRI,TEF,PAR,OBF,PAL,LOR,SIT,CRZ,ASR,ASH,PFO,CHR `
  --collect-liga --timeout 14400
```
- No PC, **COMC + Liga TAMBÉM rodam** (headful — abrem Chrome, **não feche**) → 4 fontes.
- `--collect-liga` dispara a coleta ao vivo da Liga. `--timeout 14400` = 4h (MYP é o
  gargalo; 20 sets ≈ ~20-24 edições).
- A entrega já sai **sem a coluna Valorização** (#14).
- Garanta a `POKEMONTCG_API_KEY` no ambiente (acelera o MYP).

## 5. Aprendizados do ambiente NUVEM (pra próxima sessão nuvem)
- **COMC e Liga NÃO rodam na nuvem**: precisam de Chrome **headful** (janela), e o
  container é headless (sem `DISPLAY`). Só no PC. (Não tente Xvfb — IP datacenter +
  Cloudflare = bloqueio provável.)
- **CardTrader**: API + token (`CT_JWT`, 619 chars) **funcionam** na nuvem. Teve um
  apagão **500 de ~15 min** hoje (lado deles, transitório — o site caiu p/ todos).
- **MYP**: cloudscraper fingerprint firefox pega **200** no mypcards… **até o IP ser
  throttlado** após scan pesado (vira **403**). Faça **1 scan grande por sessão**;
  evite re-fetches de catálogo no mesmo IP.
- **Preço TCG**: `tcgcsv.com` e `pokemontcg.io` dão **200** na nuvem (sem key).
- **Deps**: `pip install -r requirements.txt` de cada repo no python do container
  (não há `.venv` na nuvem; o orquestrador cai no `sys.executable`).
- **Paralelizar MYP (mypcards) + CT (cardtrader) é seguro** (sites diferentes). O
  "sequencial obrigatório" é só p/ COMC/Liga (mesmo IP, headful) — não pros 2 de API.

## 6. Pendências / decisões abertas
- [ ] **Rodar o scan dos 20 sets** (PC §4, ou nuvem quando o 403 esfriar) — decisão do operador.
- [ ] **Confirmar substrings MYP** dos 4 SWSH no próximo run sem bloqueio (esperado OK).
- [ ] *(Opcional)* Adicionar **SV base** com `myp=None` se quiser ele na lista (fica MYP-cego).
- [ ] *(Opcional, bug pequeno)* **Cross-source**: MYP escreve set "SV06: Twilight
  Masquerade" e o CT "twm"; o `cross_source.py` não reverte o nome do MYP pro código
  canônico, então cartas como **Sinistcha ex** (nas 2 fontes) não aparecem lado-a-lado.

## 7. Último resultado entregue (referência)
Scan de 16 sets (≈20 edições) na nuvem, MYP+CT: **29 deals** (8 CardTrader **preço
real/confiável** + 21 MYP **preço estimado** `.estat-tcg`, validar manual). Entregue
como tabela no chat — **não versionado** (regra: dados de scan não entram no repo).
Apoio local efêmero em `outputs/` (perde-se no fim do container).
