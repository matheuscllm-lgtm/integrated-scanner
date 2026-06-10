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

- `--profile quick` (padrão): só os principais sets de Scarlet & Violet
  (Prismatic, Surging Sparks, Journey Together, Stellar Crown, Twilight
  Masquerade, Shrouded Fable, Paldean Fates, 151). ~1h-2h no total.
- `--profile full`: o catálogo inteiro de cada fonte. Leva HORAS (o MYP
  sozinho varre ~348 edições a ~7 min cada). Use com a tarde livre.
- `--sources myp,ct,comc,liga`: escolhe quais fontes rodar (padrão: todas).
- `--skip-scan`: NÃO roda nada; só re-lê os resultados mais recentes que cada
  scanner já gerou e monta a tabela unificada. Útil pra re-ver dados de hoje.
- `--notorious-only`: só cartas de Pokémon notórios (lista em `notorious.py`).
- `--min-margin 40`: muda o corte de margem (em PERCENT; padrão 30).
- `--fx 5.30`: fixa o câmbio na mão (senão ele é inferido do output do
  CardTrader; último recurso = 5.20).

A entrega é a **tabela markdown impressa no terminal/chat** (todos os deals,
ordenados por margem). O `.md` e o `.xlsx` em `outputs/` são só apoio local.

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
run_integrated.py   orquestrador: subprocess por fonte + timeout + log por fonte
normalize.py        leitores por fonte → schema unificado + heurística de valorização
notorious.py        lista curada de Pokémon notórios + matcher por palavra inteira
delivery.py         tabela markdown completa + xlsx de apoio + resumo por fonte
tests/              26 testes (matcher, convenções de margem, status por fonte)
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
