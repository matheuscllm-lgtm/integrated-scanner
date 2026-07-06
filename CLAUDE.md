# CLAUDE.md — integrated-scanner

Instruções para qualquer sessão Claude Code (local ou nuvem) que trabalhe neste repo.
O operador (Matheus) é médico, não-programador: explique termos técnicos em linguagem
simples (há um glossário logo abaixo) e seja preciso ao mesmo tempo.

> **O que é isto, em uma frase:** um "maestro" que roda os seus 4 scanners de
> cartas avulsas (MYP, CardTrader, COMC e Liga), junta os resultados de todos
> numa tabela única com as mesmas colunas, e marca com ⭐ as cartas de Pokémon
> famosos (Charizard, Umbreon, Gengar...) que historicamente têm mais demanda.

## 🛰️ Convenções da frota (cross-scanner)

> **Manual completo** (repo privado): https://github.com/matheuscllm-lgtm/scanners-commons — erros comuns, referências de preço, chaves, GitHub Actions e modelo de entrega de TODOS os scanners. Cópia-mestra local (PC do operador): `C:\Users\mathe\scanners-commons\`.

Invariantes que valem para TODOS os scanners:

- **Margem BRUTA, mínimo 30%** — só `(revenda − compra)/compra`, sem nenhuma taxa embutida (frete, cartão, IOF — o operador calcula por fora).
- **Piso de relevância R$50 (~US$10) — SÓ para cartas avulsas (singles).** Produtos SELADOS não têm piso (decisão do operador, 2026-06-27); lá o único critério é a margem ≥30%.
- **Só Near Mint** — condição por match EXATO `== "NM"`, nunca substring (já vazou SP).
- **Nunca inventar preço** — fonte falhou → marca fallback/erro e segue; jamais fabrica número.
- **Nunca recomendar compra** — o scanner reporta margem, flags e fontes; a decisão de capital é do operador.
- **Entrega = tabela markdown no chat** (nunca XLSX/CSV por padrão), gerada pela ferramenta do repo — nunca montada à mão —, mostrando TODAS as linhas (aprovadas + rejeitadas). Coluna `Carta` = nome + número; coluna `Links` combinada = `[oferta](url) · [TCG/referência](url)`.
- ⚠️ **Convenção de threshold:** percentual inteiro (`30`) = MYP, Liga, eBay; fração (`0.30`) = CardTrader, COMC, Selados.

Erros recorrentes (3 famílias — detalhe no manual):

1. **Segredo/ambiente:** BOM/zero-width numa chave → crash latin-1 no header → scan "verde mas vazio". Setar sem BOM (`printf '%s' 'KEY' | gh secret set`) **e** sanitizar ao ler no código (`.strip()` NÃO tira BOM).
2. **Git:** branch ou `main` local defasado por squash-merge PARECE pendência. O teste real de "já mergeado" é `git diff --stat origin/main <branch>` estar vazio (não `git merge-base`).
3. **Honestidade de preço:** inflação de referência, fallback tratado como real, NM frouxo → sempre validar versão/condição e rotular fallback.

**Este scanner:** ORQUESTRADOR das 4 fontes de singles (MYP, CardTrader, COMC, Liga) — não tem fonte de preço própria; aciona cada scanner por subprocess, traduz a convenção de threshold de cada fonte e unifica a entrega. Sem chaves próprias (as chaves moram nos repos das fontes; `POKEMONTCG_API_KEY` acelera o MYP).

## Glossário rápido (termos técnicos usados aqui)

- **Orquestrador**: o programa que coordena os outros — aqui, `run_integrated.py`.
- **Subprocess (subprocesso)**: cada scanner roda como um programa separado,
  exatamente como se você tivesse aberto o terminal dele e digitado o comando.
  O integrado NÃO mexe no código dos 4 scanners — só os aciona e lê o resultado.
- **venv (ambiente virtual)**: a "caixinha" de Python de cada projeto, com as
  bibliotecas dele. Cada scanner usa o próprio venv; o integrado tem o dele.
- **Threshold (limiar)**: o corte mínimo de margem pra uma carta aparecer.
- **FX (câmbio)**: a taxa usada pra converter dólar ↔ real.
- **Headful**: navegador de verdade, com janela visível na tela (o oposto de
  "headless", invisível). COMC e Liga precisam disso pra passar pelo Cloudflare
  (o "porteiro" anti-robô do site). Quando um passo é headful, **não feche a
  janela do Chrome** que abrir.
- **Stub**: código "de mentirinha" que ocupa o lugar de uma função real ainda
  não construída. (A Liga JÁ NÃO usa stub: desde 2026-06-10 tem coletor ao
  vivo de verdade — ver a tabela de status abaixo.)
- **Sidecar**: arquivo pequeno que acompanha o resultado principal com
  metadados sobre ele (ex.: o JSON do COMC que diz quantos deals o scan achou,
  ou o `liga_trusted.json` que marca que o report da Liga veio de CSV real).

## Como rodar ("rodar o scanner integrado")

### Setup (1ª vez num ambiente novo)

```bash
python -m venv .venv
pip install -r requirements.txt
```

Dependências do integrado (as libs dos 4 scanners NÃO são necessárias aqui —
eles rodam como subprocess com os próprios venvs): `pandas`, `openpyxl`
(ler/escrever os XLSX), `fastapi` + `uvicorn` (API HTTP) e `httpx2` (TestClient
do FastAPI — o `httpx` foi trocado por `httpx2` pro TestClient; ver nota no
`requirements.txt`, não "consertar" de volta).

### Onde o integrado encontra os 4 repos-fonte

O `normalize.py` resolve a base dos repos dinamicamente
(`_resolve_base()`/`_resolve_repo()`):

1. env **`SCANNERS_BASE`** = override explícito;
2. senão, `C:\Users\mathe` se existir (layout canônico do PC do operador);
3. senão, os repos são procurados como **IRMÃOS** deste repo (ex.:
   `/home/user/integrated-scanner` + `/home/user/myp-arbitrage-scanner`) —
   é assim que funciona numa sessão de nuvem/container, sem editar nada.

A pasta da Liga aceita **dois nomes** (alias de clone): `liga-pokemon-scanner`
(nome local no PC do operador) OU `liga-cards-scanner` (nome do repo no GitHub).

### Comando do dia a dia

```powershell
# PC do operador (Windows):
cd C:\Users\mathe\integrated-scanner
.venv\Scripts\python.exe run_integrated.py --profile quick
```

```bash
# Nuvem/Linux (repos-fonte clonados como irmãos):
python run_integrated.py --profile quick
```

### Flags

- `--profile quick` (padrão): os principais sets de Scarlet & Violet
  (Prismatic, Surging Sparks, Journey Together, Stellar Crown, Twilight
  Masquerade, Shrouded Fable, Paldean Fates, 151) e, no MYP, também os da
  era Mega Evolution — Ascended Heroes, Perfect Order e Chaos Rising
  (pedido do operador 2026-06-10: são os que mais têm bons hits no MYP).
  ~1h-2h no total.
- `--profile full`: o catálogo inteiro de cada fonte. Leva HORAS (o MYP
  sozinho varre ~348 edições a ~7 min cada). Use com a tarde livre.
- **`--sets PRE,SSP,SCR` (varredura COORDENADA — novidade 2026-06-21):** os 4
  scanners varrem EXATAMENTE os mesmos sets, cada um traduzindo o código pra
  sua convenção (ver "Varredura coordenada" abaixo). Mutuamente exclusivo com
  `--profile`. Aceita também `quick`/`full` como valor (`--sets quick`).
- **`--collect-liga`:** dispara a COLETA ao vivo da Liga (HEADFUL — abre Chrome)
  pros sets do escopo ANTES de ler. **Opt-in**: sem isto, a Liga só consome o
  CSV existente e AVISA se ele não cobre o escopo. **Não use de madrugada sem
  supervisão** (Chrome headful pode travar; tem timeout próprio e isola — se
  falhar, o run continua com as outras 3 fontes).
- `--sources myp,ct,comc,liga`: escolhe quais fontes rodar (padrão: todas).
- `--skip-scan`: NÃO roda nada; só re-lê os resultados mais recentes que cada
  scanner já gerou e monta a tabela unificada. Útil pra re-ver dados de hoje.
  ⚠️ Em `--skip-scan`, `--sets`/`--collect-liga` são IGNORADOS (avisado) — a
  releitura não filtra por set (as fontes não expõem código de set por linha).
- `--liga-report <path>` (só faz sentido com `--skip-scan`): aponta um report
  da Liga vindo de **CSV REAL**; sem isso a Liga é pulada em `--skip-scan`
  (reports antigos são mock — ver o sidecar `liga_trusted.json` abaixo).
- `--notorious-only`: só cartas de Pokémon notórios (lista em `notorious.py`).
- `--min-margin 40`: muda o corte de margem unificado (em PERCENT; padrão 30).
  ⚠️ **PISO EFETIVO de 30%**: CT e MYP filtram a 30% no scan-time (threshold
  hardcoded), então `--min-margin` **abaixo de 30 NÃO traz** deals de 20-30%
  dessas fontes — só afrouxa o corte final sobre o que já passou o scan a 30%.
- `--timeout <segundos>`: sobrescreve o timeout por fonte (use em escopos
  grandes — `--sets` com muitos sets herda o timeout de "quick").
- `--fx 5.30`: fixa o câmbio na mão (senão ele é inferido do output do
  CardTrader; último recurso = 5.20).

### Skill `/auto` (`.claude/commands/auto.md`)

O repo tem uma única skill/command: **`/auto`** — o modo autônomo master da
frota (executa a tarefa ponta a ponta com checkpoints, prova real em cada
camada e os 4 freios duros definidos no próprio arquivo). É o mesmo contrato
`/auto` sincronizado nos repos da frota; leia o arquivo antes de operar nesse modo.

## Varredura coordenada por set (`set_registry.py`)

> **O problema que isto resolve:** antes, cada fonte tinha a sua lista de sets
> embutida, e elas NÃO coincidiam (o CT varria 8 sets, o MYP 11, a Liga o que
> tivesse no CSV). A "tabela unificada" então misturava sets diferentes por
> fonte. Agora um **código canônico de set** (o oficial: `PRE`, `SSP`, `SCR`...)
> é traduzido pra convenção de CADA scanner, então `--sets PRE,SSP` faz os 4
> varrerem EXATAMENTE Prismatic Evolutions e Surging Sparks.

As 4 fontes nomeiam set de jeitos diferentes (tudo verificado no código de cada
repo e travado em testes — `tests/test_set_registry.py`):

| Fonte | Como nomeia o set | Ex.: Prismatic / 151 |
|---|---|---|
| **Liga** | código oficial (= nossa chave canônica) | `PRE` / `MEW` |
| **MYP** | substring EXATA do título EN | `Prismatic` / `151` |
| **CardTrader** | código próprio do CT | `pre` / `mew` |
| **COMC** | scaneia por ERA + allowlist `--sets <abbrev>` | `(recent, PRE)` / `(recent, MEW)` |

> ⚠️ A substring do MYP é guardada EXATA no registry (`Surging`, não `Surging
> Sparks`; `Journey`, não `Journey Together`) — são as que já funcionam em
> produção. **Nunca deduzir** substring/alias de set por conta (lição do
> ASI-Evolve: aliases deduzidos por LLM saíram alucinados; a mesma lição vale
> pro cross-source, que por isso não usa fuzzy de nome).

> ⚠️ Código CT do CardTrader: o CT casa `--sets` contra o `code` da expansão
> (`pre`, `ssp`, `mew`...), que é o sistema de codes do PRÓPRIO CardTrader —
> confirmado no alias map `SET_ALIAS_TO_PTCG` (a chave é o code CT). NÃO é o
> `sv8pt5`/`sv3pt5` do `config.yaml`/`PRIORITY_SET_CODES` (esses são ptcg ids,
> usados no scan diário do CT, não no `--sets`).

### Cobertura atual do registry (20 sets)

O registry hoje tem **20 sets** em 3 blocos (a lista viva, com a cobertura de
cada fonte, sai do próprio código — `set_registry.entries()` — e da API em
`GET /sets`; não confie em cópia manual):

- **13 SV**: os 8 do quick (PRE, SSP, JTG, SCR, TWM, SFA, PAF, MEW) + 5 extras
  fora do quick, acessíveis via `--sets` (DRI, TEF, PAR, OBF, PAL — atenção:
  codes CT de OBF/PAL são `sv3`/`sv2`).
- **4 SWSH** (adicionados no PR #19; codes CT VERIFICADOS via API
  `/expansions`: `lorg`/`sit`/`crz`/`astr`): LOR, SIT, CRZ, ASR. Liga só cobre
  LOR (código `LOR`) e SIT (código Liga = `STB`); CRZ/ASR sem entrada na Liga.
  **COMC não cobre nenhum SWSH** (sem slug em `comc_set_slugs.json`). No MYP a
  substring é o nome canônico EN; subtítulos únicos → substring errada = NO-OP
  inofensivo (casa 0 edições), nunca escaneia set errado — por isso o
  "Scarlet & Violet" base NÃO entra (colidiria com todos os SV).
- **3 ME**: ASH, PFO, CHR — ver bloco abaixo.

**Era Mega Evolution (Ascended Heroes / Perfect Order / Chaos Rising) = só MYP.**
Chaves canônicas internas `ASH`/`PFO`/`CHR` (ME não tem código oficial
consolidado). Liga e COMC não cobrem ME (sem entrada / sem slug); e como o
pokemontcg.io tem 0% de preço TCG REAL na era ME, o CT também só pegaria
fallback estat lá. Então ME roda só no MYP (que trata isso nos baldes
"supranumerário/validar manual"); nas outras fontes ele **pula COM NOTA** no
status honesto — nunca silencioso, nunca erro.

## 🔀 Mesma carta em ≥2 fontes — preço lado a lado (`cross_source.py`)

> **O que isto resolve, em uma frase:** antes, a MESMA carta (ex.: Umbreon ex
> 161/131 de Prismatic) aparecia como até 4 linhas SOLTAS na tabela — uma por
> fonte — espalhadas por margem. Você não via de relance "essa carta está mais
> barata em qual fonte?". Agora, **logo depois** da tabela completa, há uma
> seção que junta essas linhas numa só, com **o preço de cada fonte lado a
> lado** (⬅ marca a mais barata) — pra escolher onde comprar.

A seção é **ADITIVA**: não substitui nem reordena a tabela plana (a regra do
operador continua sendo mostrar TODOS os deals). Ela só DESTACA as cartas que
apareceram como deal (≥ corte) em **2 ou mais fontes**.

**Como o casamento é feito (e por que é conservador):**

- **Âncora forte = set canônico + número de coleção.** Cada fonte escreve o set
  na sua convenção; o `cross_source.py` reverte pro código canônico via
  `set_registry.py` (o caminho inverso do `--sets`). Dentro de um set, o número
  de coleção é ~único → mesma `(set, número)` = mesma carta, alta confiança.
- **Número normalizado** entre convenções: `173/165` = `173` = `013`→`13`;
  prefixo de letra preservado (`TG12`, variantes `a/b`).
- **Liga não exporta número** no report → só casa por **(set + nome)**. Isso é
  mais fraco (duas raridades do mesmo Pokémon no mesmo set podem colidir) → sai
  **sempre marcado `validar`**.
- **Colisão de número entre cartas DIFERENTES** (mapeamento furado de uma fonte
  mapeia, ex., `#161` como Espeon enquanto duas outras dizem Umbreon): os nomes
  são comparados por **subconjunto de tokens** (`umbreon` ⊆ `umbreon ex` = mesma
  carta; `umbreon ex` vs `espeon ex`/`umbreon v`/`mr rime` = cartas diferentes).
  Cartas diferentes que colidem num número são **separadas** — o match real
  sobrevive e o mapeamento furado **some** do cross-source, em vez de virar uma
  linha enganosa (nome de uma carta + preço de outra).
- **Nunca chuta:** set que não resolve com segurança, ou carta numa fonte só,
  **não entra** na seção (fica só na tabela plana). Sem fuzzy de nome (lição do
  ASI-Evolve, já citada acima) — só igualdade normalizada.
- **Honestidade dura:** a seção compara só cartas que JÁ são deal ≥ corte em cada
  fonte. Um preço menor PORÉM abaixo do corte noutra fonte **não** aparece — está
  dito no cabeçalho da seção. O integrado **não decide compra**: ranqueia (pela
  margem da compra mais barata), põe o preço lado a lado e flagea `validar`.

## ⚠️ Armadilha nº 1: convenções de threshold OPOSTAS

Cada scanner inventou a própria convenção, e elas são INCOMPATÍVEIS:

| Fonte      | Convenção            | 30% se escreve... |
|------------|----------------------|--------------------|
| CardTrader | FRAÇÃO               | `0.30`             |
| COMC       | FRAÇÃO               | `0.30`             |
| MYP        | PERCENT inteiro      | `30`               |
| Liga       | PERCENT (hardcoded)  | (fixo no código)   |

Passar `30` pro CardTrader = pedir margem de 3000% = zero resultados, sem
erro nenhum. O orquestrador já passa o valor certo pra cada um — se for mexer
nos comandos, releia esta tabela antes.

## ⚠️ Armadilha nº 2: cada fonte calcula "margem" numa base diferente

MYP e Liga dividem o lucro pelo preço de COMPRA; CardTrader e COMC dividem
pelo preço de REVENDA. Pra tabela unificada fazer sentido, a margem é
**recalculada** a partir dos preços brutos, sempre na mesma fórmula:

```
Margem bruta % = (preço de revenda no TCGPlayer − preço de compra) ÷ preço de compra × 100
```

Sem nenhuma taxa embutida (sem frete, sem taxa de venda, sem IOF) — regra
canônica do operador; as taxas você calcula por fora. Como essa base
(compra) sempre dá um número maior ou igual à base "revenda", nenhum deal
que passou no corte de 30% do scanner original é perdido na unificação.

## Status honesto de cada fonte

| Fonte | Estado | Observações |
|---|---|---|
| **MYP** | funcionante | mypcards.com vs TCGPlayer, preços em R$. Não informa estoque da oferta (coluna Qtd = "—"). Raridade pouco confiável (SIR pode vir como "Comum" — fica em nota). **É o gargalo do quick (~71 min)**: defina `POKEMONTCG_API_KEY` (key grátis em dev.pokemontcg.io; `$env:POKEMONTCG_API_KEY="..."` ou User env var) — elimina o throttle e ativa o sleep adaptativo do MYP v5.11.2 (estimativa: quick cai pra ~45-55 min). Link TCG por linha vem da coluna `TCG URL` do XLSX (v5.11.2+); XLSX antigo cai num link de busca por nome. **Preço TCG real do MYP tem DUAS marcações** desde o MYP v5.15+: `real (tcgcsv)` e `real (pokemontcg)` — o `normalize.py` reconhece as duas como REAL (fix #20: checar só por "pokemontcg" perdia o tcgcsv real; não regredir). Fallback `.estat-tcg` continua fallback. |
| **CardTrader** | funcionante | Europa vs TCGPlayer. Emite Chase Tier nativo (entra na tabela unificada) e um score de valorização nativo que hoje é só de uso interno — a coluna Valorização foi removida da entrega (ver "Colunas" abaixo). Validação de preço LIVE nos top 30. |
| **COMC** | funcionante, HEADFUL | Abre uma janela do Chrome de verdade (~8 min por era) — **não feche a janela**. Tese value-buy: o mercado COMC↔TCG é o mesmo, então deals ≥30% são raros (honesto: pode vir 0). Quando o scan termina com 0 deals, o status no resumo é **"ok (0 deals)"** (lido do sidecar JSON `comc_deals_{era}_latest.json`, campo `count`); **"indisponível"** é reservado pra quando NÃO há output nenhum (nem CSV nem sidecar). |
| **Liga** | funcionante, HEADFUL (2 passos) | Desde 2026-06-10 a Liga tem coletor AO VIVO no repo dela (patchright + Chrome headful, passa o Cloudflare). **Passo 1**: rodar a coleta no repo da Liga — no PC do operador: `cd C:\Users\mathe\liga-pokemon-scanner; .venv\Scripts\python.exe src\collect_liga_live.py --sets PRE SSP --no-report` (abre janela do Chrome — não feche; gera `data/liga_offers.csv`). **Passo 2**: o integrado detecta o CSV e roda a Liga sozinho (preços reais do pokemontcg.io). Sem o CSV, a fonte é pulada com aviso. Se o CSV tiver **mais de 48h**, o resumo mostra um aviso de "CSV velho — considere re-coletar" (aviso, não bloqueio: preços da Liga mudam diário). **Os reports antigos da Liga vêm de dados MOCK (demonstração) e nunca entram na tabela.** |

**Sidecar de confiança da Liga (`outputs/liga_trusted.json`):** quando um run
do integrado roda a Liga com sucesso a partir de CSV real, ele grava esse
sidecar apontando o report gerado. É o mecanismo que separa report real de
report mock; em `--skip-scan`, sem sidecar/report deste run, a Liga sai
"indisponível" com instrução — a saída de escape é o `--liga-report` (aponta
manualmente um report que você SABE que veio de CSV real).

## Colunas da tabela unificada

Fonte | Carta | Set | Nº | Raridade | Chase Tier | Notório | Compra (R$) |
Compra (US$) | FX | Ref TCG (R$) | Ref TCG (US$) | Margem bruta % | Lucro (R$) |
Qtd | Notas | Link oferta | Link TCG

> **Entrega no chat vs. XLSX:** na **tabela markdown de entrega**, as duas
> últimas colunas (`Link oferta` + `Link TCG`) viram **uma coluna `Links` só**,
> no formato `[oferta](url) · [TCG](url)` — modelo de tabela do MYP, padrão
> cross-scanner (operador 2026-06-19). O **XLSX de apoio mantém as 2 colunas de
> URL cruas separadas** (pra reimportar). Não monte a tabela à mão: a entrega
> sai do `delivery.build_markdown`.

- **Notório**: ⭐ + nome quando a carta é de um Pokémon da lista curada
  (`notorious.py` — 60 entradas hoje, com racional comentado). É informação
  separada, explícita — não entra no ranqueamento (que é por margem bruta).
  > Nota: a coluna **Valorização (0-100)** foi REMOVIDA da entrega (operador,
  > 2026-06-22 — não fazia parte do padrão cross-scanner). A heurística
  > (`compute_valorization`) continua no código pra leitura nativa do CT e uso
  > interno, mas **não aparece** na tabela markdown nem no XLSX de entrega.
- **Qtd**: estoque do vendedor, quando a fonte informa (CT e COMC sim;
  MYP e Liga não → "—").
- **FX**: o câmbio usado NAQUELA linha (CT: implícito nos preços da própria
  linha; Liga: do report; MYP/COMC: o FX global do run).

## 📤 Entrega de resultados (MANDATÓRIO)

A entrega é a **tabela markdown impressa no terminal/chat** (todos os deals,
ordenados por margem), gerada pelo `delivery.build_markdown` — **nunca montada
à mão**, nunca XLSX/CSV por padrão (arquivo só se o operador pedir
explicitamente). O `.md` e o `.xlsx` em `outputs/` são só apoio local. Logo
depois da tabela completa vem a seção cross-source (aditiva) e o resumo com o
status honesto por fonte.

### O integrado NUNCA decide compra

Ele ranqueia, flagea e explica. Quem decide capital é o operador — por isso
não existe coluna "COMPRAR", e as linhas incertas saem com flag `validar` /
nota de limitação em vez de veredito.

## Testes e CI

```powershell
# PC do operador:
.venv\Scripts\python.exe -m pytest tests/ -q
```

```bash
# nuvem/Linux:
python -m pytest tests/ -q
```

88 testes (registry/escopo, cross-source, matcher, margem, status, API/store).

⚠️ **Use `python -m pytest`, nunca o `pytest` pelado**: o `python -m` adiciona a
raiz do repo ao sys.path, então `import api`/`import cross_source` resolvem; com
`pytest` pelado o `tests/test_api.py` quebra na coleta (`ModuleNotFoundError:
api`). A pegadinha está documentada no próprio `ci.yml`.

**CI** (`.github/workflows/ci.yml`): job único "pytest + smoke (Python 3.11)" —
`pip install -r requirements.txt` + `python -m pytest -q`, seguido de um smoke
offline do orquestrador (`python run_integrated.py --skip-scan --sources
myp,ct`: sem rede e sem outputs reais, cada fonte cai no ramo "sem output" e a
entrega sai vazia com exit 0 — exercita imports + pipeline de
normalização/entrega ponta a ponta). Dispara em push na `main` e em todo PR.

## Arquitetura (pra quem for mexer no código)

```
run_integrated.py   orquestrador: escopo coordenado + subprocess por fonte + alimenta o store
set_registry.py     registro canônico de sets (20) + tradutores p/ convenção de cada fonte
cross_source.py     casa a MESMA carta entre fontes (set canônico + número) p/ preço lado-a-lado
normalize.py        leitores por fonte → schema unificado + resolução dos repos (SCANNERS_BASE) + heurística de valorização
notorious.py        lista curada de Pokémon notórios + matcher por palavra inteira
delivery.py         tabela markdown completa + xlsx de apoio + resumo por fonte + seção cross-source
api_store.py        store JSON unificado (alimentado pelo run; lido pela API)
api.py              API HTTP FastAPI (expõe deals/sets/status; dispara scan)
tests/              88 testes (registry/escopo, cross-source, matcher, margem, status, API/store)
outputs/            resultados, logs e deals_store.json (não versionado)
```

Falha de uma fonte NÃO derruba as outras: cada uma tem timeout e log próprios
(`outputs/logs/`), e o status (ok/falhou/timeout/indisponível) aparece no
cabeçalho da entrega.

## API HTTP — "APIs expostas E alimentadas" (`api.py` + `api_store.py`)

> **O que é, em uma frase:** uma "tomada" HTTP no scanner integrado. Programas
> (ou você, no navegador) podem PERGUNTAR os deals unificados, o catálogo de
> sets e o status — e até DISPARAR um scan coordenado — por URLs, sem terminal.

Como funciona o "alimentadas E expostas":
- **Alimentadas:** todo run do `run_integrated.py` GRAVA `outputs/deals_store.json`
  (deals unificados + status por fonte + metadados do run). É o `api_store.py`,
  gravação atômica + cópia histórica `deals_store_<stamp>.json`.
- **Expostas:** o `api.py` (FastAPI) LÊ esse store e serve por HTTP.

Subir o servidor:
```powershell
cd C:\Users\mathe\integrated-scanner
.venv\Scripts\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8077
```
Depois abra **http://127.0.0.1:8077/docs** (Swagger UI interativo, auto-gerado).

Endpoints:
| Método | Rota | O que faz |
|---|---|---|
| GET | `/health` | liveness |
| GET | `/` | info + resumo do último run |
| GET | `/sets` | catálogo canônico de sets + como cada fonte cobre cada um |
| GET | `/sources` | as 4 fontes + status do último run (flag headful) |
| GET | `/deals` | deals unificados do store; filtros `?source=&set=&min_margin=&notorious=&q=&limit=` |
| GET | `/status` | metadados do último run + status honesto por fonte |
| POST | `/scan` | DISPARA scan coordenado em background (alimenta o store); body `{sets, sources, min_margin, collect_liga, notorious_only}` → `job_id` |
| GET | `/scan/{job_id}` | status do job de scan |

Segurança/escopo: o `POST /scan` roda `run_integrated.py` em background; fontes
**headful** (COMC/Liga) abrem Chrome — por isso o default é `["myp","ct"]` e
COMC/Liga exigem opt-in explícito no corpo (Liga headful real só com
`collect_liga: true`). A API **só EXPÕE** o que o pipeline produz: continua
valendo "RANQUEIA/FLAGEIA, NUNCA decide compra"; margem bruta sem taxas.

## Repos das fontes (não editar a partir daqui)

Caminhos no **PC do operador** (na nuvem, os repos são clonados como irmãos
deste — ver "Onde o integrado encontra os 4 repos-fonte"):

| Fonte | Repo GitHub (`matheuscllm-lgtm/…`) | Pasta local (PC do operador) | Nota |
|---|---|---|---|
| MYP | `myp-arbitrage-scanner` | `C:\Users\mathe\myp-arbitrage-scanner\` | v5.11+ |
| CardTrader | `card-trader-scanner` | `C:\Users\mathe\card-trader-scanner\` | v2.13+ |
| COMC | `scanner-comc` | `C:\Users\mathe\scanner-comc\` | ler HANDOFF.md §0 do repo dele antes de mexer |
| Liga | `liga-cards-scanner` | `C:\Users\mathe\liga-pokemon-scanner\` | nome local ≠ nome GitHub (o resolver aceita os dois); coletor ao vivo desde 2026-06-10 |

## Fluxo de desenvolvimento e segurança

- Mudanças de código/doc entram por **branch + PR** (é como todo o histórico do
  repo foi construído); não dê push direto em `main`.
- `outputs/` (resultados, logs, `deals_store.json`) é subproduto local **não
  versionado** — dados de scan ficam fora do repo.
- Este repo **não tem chaves próprias**; nunca versionar segredos. As chaves
  moram nos repos das fontes (a `POKEMONTCG_API_KEY` do ambiente só acelera o
  MYP).
- **`HANDOFF.md` e `HANDOFF02.md`** (raiz, versionados) são handoffs de sessões
  de nuvem (2026-06-20 e 2026-06-24: liberação do fluxo pós-PRs + expansão do
  registry 10→20 sets). São notas de contexto histórico — o manual canônico é
  este `CLAUDE.md`; em conflito, este arquivo e o código valem.
