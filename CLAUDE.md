# Scanner integrado de singles Pokémon

> **O que é isto, em uma frase:** um "maestro" que roda os seus 4 scanners de
> cartas avulsas (MYP, CardTrader, COMC e Liga), junta os resultados de todos
> numa tabela única com as mesmas colunas, e marca com ⭐ as cartas de Pokémon
> famosos (Charizard, Umbreon, Gengar...) que historicamente têm mais demanda.

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
  "headless", invisível). O COMC precisa disso pra passar pelo Cloudflare
  (o "porteiro" anti-robô do site).
- **Stub**: código "de mentirinha" que ocupa o lugar de uma função real ainda
  não construída. (A Liga JÁ NÃO usa stub: desde 2026-06-10 tem coletor ao
  vivo de verdade — ver a tabela de status abaixo.)
- **Sidecar**: arquivo pequeno que acompanha o resultado principal com
  metadados sobre ele (ex.: o JSON do COMC que diz quantos deals o scan achou).

## Como rodar ("rodar o scanner integrado")

```powershell
cd C:\Users\mathe\integrated-scanner
.venv\Scripts\python.exe run_integrated.py --profile quick
```

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
- `--notorious-only`: só cartas de Pokémon notórios (lista em `notorious.py`).
- `--min-margin 40`: muda o corte de margem (em PERCENT; padrão 30).
- `--timeout <segundos>`: sobrescreve o timeout por fonte (use em escopos
  grandes — `--sets` com muitos sets herda o timeout de "quick").
- `--fx 5.30`: fixa o câmbio na mão (senão ele é inferido do output do
  CardTrader; último recurso = 5.20).

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
> ASI-Evolve: aliases deduzidos por LLM saíram alucinados).

> ⚠️ Código CT do CardTrader: o CT casa `--sets` contra o `code` da expansão
> (`pre`, `ssp`, `mew`...), que é o sistema de codes do PRÓPRIO CardTrader —
> confirmado no alias map `SET_ALIAS_TO_PTCG` (a chave é o code CT). NÃO é o
> `sv8pt5`/`sv3pt5` do `config.yaml`/`PRIORITY_SET_CODES` (esses são ptcg ids,
> usados no scan diário do CT, não no `--sets`).

**Era Mega Evolution (Ascended Heroes / Perfect Order / Chaos Rising) = só MYP.**
Chaves canônicas internas `ASH`/`PFO`/`CHR` (ME não tem código oficial
consolidado). Liga e COMC não cobrem ME (sem entrada / sem slug); e como o
pokemontcg.io tem 0% de preço TCG REAL na era ME, o CT também só pegaria
fallback estat lá. Então ME roda só no MYP (que trata isso nos baldes
"supranumerário/validar manual"); nas outras fontes ele **pula COM NOTA** no
status honesto — nunca silencioso, nunca erro.

A entrega é a **tabela markdown impressa no terminal/chat** (todos os deals,
ordenados por margem). O `.md` e o `.xlsx` em `outputs/` são só apoio local.

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
  ASI-Evolve: alias deduzido por LLM alucina) — só igualdade normalizada.
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
| **MYP** | funcionante | mypcards.com vs TCGPlayer, preços em R$. Não informa estoque da oferta (coluna Qtd = "—"). Raridade pouco confiável (SIR pode vir como "Comum" — fica em nota). **É o gargalo do quick (~71 min)**: defina `POKEMONTCG_API_KEY` (key grátis em dev.pokemontcg.io; `$env:POKEMONTCG_API_KEY="..."` ou User env var) — elimina o throttle e ativa o sleep adaptativo do MYP v5.11.2 (estimativa: quick cai pra ~45-55 min). Link TCG por linha vem da coluna `TCG URL` do XLSX (v5.11.2+); XLSX antigo cai num link de busca por nome. |
| **CardTrader** | funcionante | Europa vs TCGPlayer. Já emite Chase Tier e score de Valorização nativos. Validação de preço LIVE nos top 30. |
| **COMC** | funcionante, HEADFUL | Abre uma janela do Chrome de verdade (~8 min por era) — **não feche a janela**. Tese value-buy: o mercado COMC↔TCG é o mesmo, então deals ≥30% são raros (honesto: pode vir 0). Quando o scan termina com 0 deals, o status no resumo é **"ok (0 deals)"** (lido do sidecar JSON `comc_deals_{era}_latest.json`, campo `count`); **"indisponível"** é reservado pra quando NÃO há output nenhum (nem CSV nem sidecar). |
| **Liga** | funcionante, HEADFUL (2 passos) | Desde 2026-06-10 a Liga tem coletor AO VIVO no repo dela (patchright + Chrome headful, passa o Cloudflare). **Passo 1**: rodar a coleta no repo da Liga — `cd C:\Users\mathe\liga-pokemon-scanner; .venv\Scripts\python.exe src\collect_liga_live.py --sets PRE SSP --no-report` (abre janela do Chrome — não feche; gera `data/liga_offers.csv`). **Passo 2**: o integrado detecta o CSV e roda a Liga sozinho (preços reais do pokemontcg.io). Sem o CSV, a fonte é pulada com aviso. Se o CSV tiver **mais de 48h**, o resumo mostra um aviso de "CSV velho — considere re-coletar" (aviso, não bloqueio: preços da Liga mudam diário). **Os reports antigos da Liga vêm de dados MOCK (demonstração) e nunca entram na tabela.** |

## Colunas da tabela unificada

Fonte | Carta | Set | Nº | Raridade | Chase Tier | Notório | Compra (R$) |
Compra (US$) | FX | Ref TCG (R$) | Ref TCG (US$) | Margem bruta % | Lucro (R$) |
Qtd | Valorização (0-100) | Notas | Link oferta | Link TCG

> **Entrega no chat vs. XLSX:** na **tabela markdown de entrega**, as duas
> últimas colunas (`Link oferta` + `Link TCG`) viram **uma coluna `Links` só**,
> no formato `[oferta](url) · [TCG](url)` — modelo de tabela do MYP, padrão
> cross-scanner (operador 2026-06-19). O **XLSX de apoio mantém as 2 colunas de
> URL cruas separadas** (pra reimportar). Não monte a tabela à mão: a entrega
> sai do `delivery.build_markdown`.

- **Notório**: ⭐ + nome quando a carta é de um Pokémon da lista curada
  (`notorious.py`, ~55 ícones com racional comentado). O flag NÃO infla o
  score de valorização — é informação separada, explícita.
- **Valorização (0-100)**: heurística portada do CardTrader scanner v2.13
  (raridade + idade do set + patamar de preço). SEM série histórica de preço —
  é triagem, não previsão. Pro CT o score vem pronto do scanner; pra
  MYP/COMC/Liga é calculado aqui com a MESMA fórmula (comparável).
- **Qtd**: estoque do vendedor, quando a fonte informa (CT e COMC sim;
  MYP e Liga não → "—").
- **FX**: o câmbio usado NAQUELA linha (CT: implícito nos preços da própria
  linha; Liga: do report; MYP/COMC: o FX global do run).

## O integrado NUNCA decide compra

Ele ranqueia, flagea e explica. Quem decide capital é o operador — por isso
não existe coluna "COMPRAR" e o score vem sempre com a nota de limitação.

## Arquitetura (pra quem for mexer no código)

```
run_integrated.py   orquestrador: escopo coordenado + subprocess por fonte + timeout + log
set_registry.py     registro canônico de sets + tradutores p/ convenção de cada fonte
cross_source.py     casa a MESMA carta entre fontes (set canônico + número) p/ preço lado-a-lado
normalize.py        leitores por fonte → schema unificado + heurística de valorização
notorious.py        lista curada de Pokémon notórios + matcher por palavra inteira
delivery.py         tabela markdown completa + xlsx de apoio + resumo por fonte + seção cross-source
tests/              62 testes (registry/escopo, cross-source, matcher, margem, status)
outputs/            resultados e logs (não versionado)
```

Falha de uma fonte NÃO derruba as outras: cada uma tem timeout e log próprios
(`outputs/logs/`), e o status (ok/falhou/timeout/indisponível) aparece no
cabeçalho da entrega.

Rodar os testes:

```powershell
.venv\Scripts\python.exe -m pytest tests/ -q
```

## Repos das fontes (não editar a partir daqui)

- MYP: `C:\Users\mathe\myp-arbitrage-scanner\` (v5.11+)
- CardTrader: `C:\Users\mathe\card-trader-scanner\` (v2.13+)
- COMC: `C:\Users\mathe\scanner-comc\` (ler HANDOFF.md §0 antes de mexer)
- Liga: `C:\Users\mathe\liga-pokemon-scanner\` (coletor ao vivo desde 2026-06-10)
