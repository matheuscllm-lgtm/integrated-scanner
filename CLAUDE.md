# Scanner integrado — manual de operação

Regras de entrega e publicação: [DELIVERY_CHAT.md](DELIVERY_CHAT.md).
O integrado chama os scanners MYP, CardTrader, COMC e Liga. MYP e CardTrader
são as fontes padrão. Ele organiza preços e alertas; a decisão de compra é do operador.

## Instalação

Python 3.12, ambiente virtual e `pip install -r requirements.txt`.
Cada fonte deve estar em um clone irmão deste repositório, ou abaixo do diretório
definido em `SCANNERS_BASE`. No PC do operador, o layout legado é
`C:\Users\mathe\{integrated-scanner,myp-arbitrage-scanner,card-trader-scanner,scanner-comc}`.
Liga aceita `liga-pokemon-scanner` ou `liga-cards-scanner`.
O integrado prefere o `.venv` de cada fonte; sem ele, usa seu próprio Python.
Nesse caso, instalar também as dependências das fontes no mesmo ambiente.
CardTrader exige `CT_JWT`, em seu `.env` ou no ambiente; `POKEMONTCG_API_KEY` é opcional.
Nunca versionar segredos. No Windows, a dependência CT inclui `portalocker[win32]`.

## Rodar uma coleta nova

```powershell
python run_integrated.py --profile group2 --sources myp,ct
python run_integrated.py --sets PAF,PAR --ct-provider tcgcsv
python run_integrated.py --sets PAF --myp-max-products 5 --timeout 600
```

O último comando é um **diagnóstico limitado**, identificado no título e na API.
`--myp-max-products` limita cada edição MYP; não limita o catálogo CardTrader.
`quick` mantém o escopo histórico; `full` pode levar horas.
`group2` cobre as 14 coleções escolhidas pelo operador: Paldean Fates,
Paradox Rift, Obsidian Flames, 151, Paldea Evolved, Black Bolt, White Flare,
Crown Zenith, Silver Tempest, Lost Origin, Astral Radiance, Brilliant Stars,
Fusion Strike e Evolving Skies. Substrings MYP podem corresponder a mais de
uma entrada de edição; os filtros EN/NM continuam responsabilidade da fonte.
O registry tem 25 entradas; `/sets` mostra a cobertura por fonte.
CT `obf`, `pal`, `blk`, `wht`, `brs`, `fst`, `evs` foram verificados na API
`/expansions` em 06/09/2026. Fontes sem mapeamento são puladas explicitamente.

CardTrader usa **TCGCSV por padrão**, configurável com `--ct-provider`.
MYP aceita `--myp-provider auto|tcgcsv|pokemontcg`. TCGCSV é referência de dump,
não cotação em tempo real; a entrega não inventa a data de atualização do dump.
Cada execução CT usa um diretório de estado novo e `--no-cache`.
Cada execução MYP usa saída nova; não retoma checkpoints de solicitações anteriores.
O MYP atualizado salva progresso a cada dez produtos e ao receber falha persistente,
respeita `Retry-After` e gera XLSX parcial com código 2. Retomada nativa com
`--resume` deve ser explícita, na mesma solicitação e saída, nunca preço de outro scan.

Liga só roda com `--collect-liga`, pois exige uma coleta nova com navegador.
Coleta falhou ou CSV não foi atualizado: não usar o CSV anterior.
COMC só aceita CSV/sidecar recém-produzido nas eras pedidas; exige os requisitos
de navegador do próprio repositório. Os testes ao vivo desta correção cobrem MYP/CT;
COMC/Liga precisam de validação específica no ambiente de navegador do operador.

## Formato MyP Cards

A tabela compacta apresenta número da linha, fonte, margem, compra R$,
referência US$/R$, diferença R$, carta com número, set, raridade, condição,
quantidade, flags e os dois links. O preço de referência é clicável.
Não substituir preço ou evidência ausente por zero, busca genérica ou outra carta.
Uma estimativa MYP aponta para a página MYP que a fornece.

Todas as linhas lidas permanecem na entrega, separadas em:
- Deals limpos com referência real;
- Validar manualmente;
- Fallback/estimativa;
- Rejeitados ou sem referência;
- Abaixo do corte, apenas diagnóstico.

O leitor MYP usa `All EN Cards`, evitando perder as linhas abaixo do corte.
CT preserva variante, idioma, condição, procedência, horário e validação.
Linhas CT não validadas não viram deals limpos por passar apenas no corte numérico.

As fórmulas originais das fontes não mudam: MYP usa 30% sobre a compra;
CT usa 0,30 sobre a referência. O integrado recalcula `(referência-compra)/compra`.
30% sobre a referência equivale a 42,86% sobre a compra. CT também exporta
linhas abaixo do seu corte, que permanecem identificadas e sem validação automática.
Nenhuma taxa é embutida. Diferença bruta não é lucro líquido.
O USD original e o câmbio implícito do MYP/CT são preservados.
Para fontes sem FX próprio, há consulta nova ou `--fx` explícito; não há fallback numérico antigo.

## Comparação entre lojas

O parser aceita o formato real CT `Nome (código)` e rejeita pares contraditórios.
O casamento exige set, número e nomes compatíveis, condição e idioma.
Variantes conhecidas diferentes ficam separadas. Uma variante ausente só pode
se associar a um único candidato de variante conhecida e sempre exige `validar`;
nunca conecta duas variantes diferentes. Dados ausentes e alertas na fonte
impedem marcar uma loja como a mais barata sem revisão.
Inclui também preços coletados abaixo do corte para permitir comparar a mesma
carta quando uma fonte não atingiu o limiar. Não é uma consulta exaustiva de
todas as lojas; só compara as linhas recebidas. Ofertas explicitamente rejeitadas,
STALE, API_ERROR e PRICE_CHANGED ficam fora da escolha de menor preço.

## Falhas, API e releitura histórica

Cada fonte mantém erro, log e horário. Nenhuma falha cai no último XLSX antigo.
Saída 0 = sucesso; 2 = parcial; 1 = falha/indisponibilidade total.
A API reflete `done`, `partial` ou `failed`; `/status` informa modo e limite diagnóstico.

```powershell
python -m uvicorn api:app --host 127.0.0.1 --port 8077
```

`GET /health`, `/sets`, `/sources`, `/deals`, `/status` consultam a API.
`POST /scan` aceita sets, sources, min_margin, ct_provider, myp_provider e
myp_max_products. COMC exige allow_comc; Liga exige collect_liga.
O store mantém todos os baldes. Nenhuma publicação externa é feita pelo scanner.

Reprocessamento técnico explícito, **sem tratar como coleta atual**:

```powershell
python run_integrated.py --skip-scan --sources ct --ct-output caminho/arquivo.xlsx
```

Para MYP use `--myp-output`; Liga aceita `--liga-report` proveniente de CSV real.
A releitura fica marcada como histórica, tem escopo desconhecido e store separado;
não substitui o store da coleta atual. Sem arquivo explícito, não procura o último.

## Desenvolvimento e verificação

Alterações entram por branch + PR, com testes antes do merge. O operador autorizou
merge nesta tarefa. `python -m pytest -q` roda as regressões offline.
CI verifica Linux e Windows com fixtures sintéticas; nunca publica preços ou logs
de mercado, artifacts de coleta, segredos ou resultados de scans no GitHub.
`outputs/` permanece ignorado. Handoffs antigos são contexto histórico;
este manual e DELIVERY_CHAT descrevem o comportamento vigente.
