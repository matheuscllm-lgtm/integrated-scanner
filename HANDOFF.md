# HANDOFF — assumir o comando dos scanners pelo terminal do PC

> Gerado por uma sessão Claude Code **na nuvem** em **2026-06-20**. É o ponto de
> partida pra você (Matheus) continuar no terminal do seu PC.
> **⚠️ Sem segredos aqui** (os repos são públicos): a `POKEMONTCG_API_KEY` **não**
> está escrita neste arquivo — veja a **seção 3**.

---

## 0. TL;DR — faça nesta ordem

1. **Revisar e mergear os 3 PRs draft** desta sessão → seção 2.
2. **Setar a `POKEMONTCG_API_KEY`** nos lugares que faltam → seção 3.
3. **Rodar** — local (seção 4) **ou** via GitHub Actions, agora liberado (seção 5).

---

## 1. O que esta sessão fez

- **Tornou o orquestrador integrado cross-platform.** Antes só rodava no seu
  Windows (caminhos `C:\Users\mathe\...` e `.venv\Scripts\python.exe` hardcoded);
  agora roda também na nuvem / qualquer máquina (resolve os repos como irmãos e
  cai pro interpreter disponível). → PR **integrated-scanner #5**.
- **Escopo custom = `--sets` (canônico, coordenado).** Pra rodar dentro de sets
  específicos, use `--sets PRE,SSP,SCR` — código canônico de set traduzido pra
  convenção de CADA fonte, varrendo os MESMOS sets em todas (ver
  `set_registry.py` / seção "Varredura coordenada" do CLAUDE.md). Substitui a
  ideia antiga de flags crus por fonte (`--myp-editions`/`--ct-sets`), que era
  não-coordenada e foi descartada em favor do `--sets`.
- **Resultado** é entregue como **tabela no chat** — NÃO entra no repo (é *deal
  data*). Arquivos de apoio ficam em `integrated-scanner/outputs/` (gitignored).
- **Corrigiu a nota "GitHub Actions inativo por billing"**: repos agora públicos
  → Actions é grátis (billing não bloqueia mais). **MAS** o CI ainda devolve
  preço **fallback** (runners não alcançam a pokemontcg.io) — rodar ≠ servir
  preço real; o caminho de preço real é LOCAL. → PRs **myp #52** e **asi-evolve #4**.

---

## 2. PRs abertos (draft — precisam da sua revisão/merge)

| Repo | PR | O que é | CI |
|---|---|---|---|
| `integrated-scanner` | **#5** | orquestrador roda na nuvem (cross-platform) + flags custom | sem CI no repo |
| `myp-arbitrage-scanner` | **#52** | doc: Actions voltou a valer (repos públicos) | ✅ `tests.yml` (27 verdes) |
| `asi-evolve` | **#4** | doc: CI não fica mais vermelha por billing | sem CI |

Todos na branch **`claude/sleepy-curie-5tph66`**. Pra revisar local:

```bash
git fetch origin claude/sleepy-curie-5tph66
git checkout claude/sleepy-curie-5tph66
```

São PRs **draft** — marque "Ready for review" e mergeie quando aprovar.

---

## 3. A `POKEMONTCG_API_KEY` (⚠️ segurança)

- A key **não está escrita em nenhum arquivo** porque os repos são **públicos**.
  Ela está: **(a)** no chat desta sessão e **(b)** no seu dashboard
  **dev.pokemontcg.io**. Regra dura cross-scanner: **nunca commitar a key**.
- **Onde ela precisa morar — você seta 1× em cada (a sessão da nuvem NÃO consegue
  setar secret/env na sua conta):**

  1. **GitHub Actions (pra rodar scan via workflow):** em CADA repo com workflow
     de scan (hoje: `myp-arbitrage-scanner`) → *Settings → Secrets and variables →
     Actions → New repository secret* → nome **`POKEMONTCG_API_KEY`**, valor = a key.
     Os 3 workflows do MYP já injetam o secret sozinhos.
  2. **Local no PC (Windows, persistente):**
     ```powershell
     [Environment]::SetEnvironmentVariable("POKEMONTCG_API_KEY","<sua-key>","User")
     ```
     Vale a partir do **próximo** terminal. Pra sessão atual: `$env:POKEMONTCG_API_KEY="<sua-key>"`.
  3. **Sessões Claude Code na nuvem:** env var do **environment** em
     code.claude.com → aí toda sessão futura já nasce com a key (não precisa colar).

- Sem a key o MYP roda mesmo assim, só **mais devagar** (throttle 429).

---

## 4. Rodar LOCAL (seu PC) — caminho canônico

**Busca geral num comando só (as 4 fontes, é onde COMC+Liga funcionam):**
```powershell
cd C:\Users\mathe\integrated-scanner
.venv\Scripts\python.exe run_integrated.py --profile quick
```
- Entrega = **tabela markdown no chat/terminal**. `outputs/*.md|*.xlsx` é só apoio.
- **Liga é 2 passos:** antes rode o coletor headful no repo da Liga
  (`collect_liga_live.py --sets PRE SSP ...`) pra gerar `data/liga_offers.csv`;
  o integrado lê sozinho. **COMC** abre janela do Chrome — não feche.

**Rodar uma fonte isolada (quando quiser):**
```powershell
# MYP
cd C:\Users\mathe\myp-arbitrage-scanner
python myp_arbitrage_scanner.py --editions "Ascended Heroes" --threshold 30 --min-price 50 -o results\out.xlsx
# CardTrader (threshold é FRAÇÃO: 0.30 = 30%)
cd C:\Users\mathe\card-trader-scanner
.venv\Scripts\python.exe cardtrader_scanner.py --sets pre ssp jtg --threshold 0.30 --validate-top 30 --output outputs\out.xlsx
# COMC (headful) e Liga (headful) — ver CLAUDE.md de cada repo
```

> Convenções de threshold **opostas** (não troque): CardTrader/COMC = **fração**
> (`0.30`); MYP/Liga = **percent inteiro** (`30`). O integrado já passa o certo.

---

## 5. Rodar via GitHub Actions (AGORA liberado — repos públicos)

- **Só o MYP** tem workflow que roda em runner do GitHub. CardTrader (precisa do
  `CT_JWT`), COMC e Liga (precisam de **Chrome headful** = janela visível) **não**
  rodam em runner — esses ficam no seu PC.
- **Quick MYP Scan (chunked):** aba **Actions** → *Quick MYP Scan (chunked)* →
  *Run workflow*. Ou no terminal (precisa do `gh` logado):
  ```bash
  gh workflow run quick-scan.yml
  ```
- **Pré-requisito:** o secret `POKEMONTCG_API_KEY` setado (seção 3.1).
- **Saída:** XLSX consolidado como **artifact** (baixa na página do run) — **não**
  commita deal data no repo. Cada chunk roda num runner com IP próprio (sem
  conflito de Cloudflare), ~10-15 min pras edições do quick.

---

## 6. O que roda onde (nuvem × seu PC × Actions)

| Fonte | Seu PC | Nuvem (Claude Code) | GitHub Actions |
|---|:---:|:---:|:---:|
| **MYP** | ✅ | ✅ | ✅ (quick-scan.yml) |
| **CardTrader** | ✅ | ✅ (tem `CT_JWT`) | ⚠️ precisa secret JWT |
| **COMC** | ✅ headful | ❌ Cloudflare + headful | ❌ headful |
| **Liga** | ✅ headful | ❌ Cloudflare + headful | ❌ headful |

> **As 4 fontes numa tacada só = só no seu PC** (COMC e Liga exigem janela de
> Chrome visível pra furar o Cloudflare; container/runner não têm tela).

---

## 7. Pendências / backlog

- [ ] **Mergear os 3 PRs** (seção 2).
- [ ] **Setar o secret `POKEMONTCG_API_KEY`** no `myp-arbitrage-scanner` (seção 3.1)
      pra Actions usar a key.
- [ ] **COMC + Liga**: rodar na sua máquina (headful) pra ter as 4 fontes no integrado.
- [ ] *(opcional)* **Doc drift** no `myp-arbitrage-scanner/CLAUDE.md`: diz que o quick
      "commita `results/latest-quick.md`", mas o workflow sobe como **artifact** — corrigir.
- [ ] *(opcional)* CardTrader **sem `--chase-only`** pra varredura ampla do catálogo.
- [ ] *(do CLAUDE.md da Liga)* Issue **#17** (apagar 14 branches órfãs — manual);
      arquivar repo duplicado `liga-arbitrage-scanner`; corrigir README drift.

---

## 8. Mapa dos repos (todos `matheuscllm-lgtm/...`, públicos)

| Repo | Papel |
|---|---|
| `integrated-scanner` | **maestro** — orquestra MYP+CT+COMC+Liga numa tabela só |
| `myp-arbitrage-scanner` | MYP (mypcards.com BR vs TCGplayer) — tem workflows de Actions |
| `card-trader-scanner` | CardTrader (Europa vs TCGplayer) |
| `scanner-comc` | COMC (headful, value-buy) |
| `liga-cards-scanner` | Liga Pokémon BR (headful, coletor ao vivo) |
| `ebay-arbitrage-scanner` | eBay (graded; usa PriceCharting) — independente |
| `pokemon-longterm-outlook` | score de potencial de longo prazo (não é arbitragem) |
| `asi-evolve` / `asi-main` | laboratório de evolução de código (projeto separado) |

> Regra de entrega (todos os scanners): o resultado é **tabela no chat**, gerada
> pela ferramenta do repo — **nunca** montada à mão, **nunca** arquivo por padrão.
> Margem é **bruta** (sem taxas), corte **30%**, piso ~R$50 / US$10. O scanner
> **nunca** recomenda compra: reporta margem, flags e fontes; o capital é seu.
